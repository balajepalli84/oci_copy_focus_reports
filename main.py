import io
import json
import logging
import oci
import zipfile
import gzip
import os
from datetime import datetime, timedelta
from fdk import response
import os

def clean_tmp_directory(path='/tmp'):
    try:
        # Caution: path must be '/tmp' or similar safe directory
        if path == '/tmp':
            os.system('rm -rf /tmp/*')
        else:
            # If needed to be safer for other paths
            os.system(f'rm -rf {path}/*')
        print(f"Successfully cleaned {path}", flush=True)
    except Exception as e:
        print(f'Failed to clean {path}. Reason: {e}', flush=True)


def handler(ctx, data: io.BytesIO = None):
    try:
        processed_files = []
        reporting_namespace = 'bling'
        yesterday = datetime.now() - timedelta(days=1)
        prefix_file = f"FOCUS Reports/{yesterday.year}/{yesterday.strftime('%m')}/{yesterday.strftime('%d')}"
        print(f"prefix is {prefix_file}", flush=True)
        destination_path = '/tmp'
        clean_tmp_directory(destination_path)

        dest_namespace = 'NS_ramesh' #change to your destination namespace
        upload_bucket_name = 'cost_and_usage_reports' #change to your destination bucket name

        signer = oci.auth.signers.get_resource_principals_signer()
        reporting_bucket = signer.tenancy_id
        print('Bucket is ' + reporting_bucket, flush=True)

        object_storage = oci.object_storage.ObjectStorageClient(config={}, signer=signer)

        report_bucket_objects = oci.pagination.list_call_get_all_results(
            object_storage.list_objects,
            reporting_namespace,
            reporting_bucket,
            prefix=prefix_file
        )
        print('Found ' + str(len(report_bucket_objects.data.objects)) + ' files', flush=True)

        for o in report_bucket_objects.data.objects:
            source_object_path = o.name  # e.g. FOCUS Reports/2025/04/05/0001.csv.gz
            filename = source_object_path.rsplit('/', 1)[-1]
            local_file_path = os.path.join(destination_path, filename)

            # Download the object to /tmp
            object_details = object_storage.get_object(reporting_namespace, reporting_bucket, source_object_path)
            with open(local_file_path, 'wb') as f:
                for chunk in object_details.data.raw.stream(1024 * 1024, decode_content=False):
                    f.write(chunk)

            # Determine final object name in destination
            if zipfile.is_zipfile(local_file_path):
                with zipfile.ZipFile(local_file_path, 'r') as zip_ref:
                    for extracted_name in zip_ref.namelist():
                        extracted_path = os.path.join(destination_path, extracted_name)

                        if os.path.isdir(extracted_path):
                            continue

                        os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
                        zip_ref.extract(extracted_name, destination_path)

                        # Create destination path: replace .zip with actual file name
                        dest_object_path = os.path.join(
                            os.path.dirname(source_object_path),
                            extracted_name
                        )

                        with open(extracted_path, 'rb') as extracted_file:
                            object_storage.put_object(
                                namespace_name=dest_namespace,
                                bucket_name=upload_bucket_name,
                                object_name=dest_object_path,
                                put_object_body=extracted_file
                            )
                        processed_files.append(dest_object_path)

            elif filename.endswith('.gz'):
                unzipped_filename = filename[:-3]  # Remove .gz
                dest_object_path = os.path.join(os.path.dirname(source_object_path), unzipped_filename)
                unzipped_path = os.path.join(destination_path, unzipped_filename)

                with gzip.open(local_file_path, 'rb') as f_in:
                    with open(unzipped_path, 'wb') as f_out:
                        f_out.write(f_in.read())

                with open(unzipped_path, 'rb') as f:
                    object_storage.put_object(
                        namespace_name=dest_namespace,
                        bucket_name=upload_bucket_name,
                        object_name=dest_object_path,
                        put_object_body=f
                    )
                processed_files.append(dest_object_path)

            else:
                # Not zipped, just upload as-is
                object_storage.put_object(
                    namespace_name=dest_namespace,
                    bucket_name=upload_bucket_name,
                    object_name=source_object_path,
                    put_object_body=open(local_file_path, 'rb')
                )
                processed_files.append(source_object_path)

    except Exception as ex:
        logging.getLogger().error('Error during processing: ' + str(ex))

    return response.Response(
        ctx,
        response_data=json.dumps({
            "message": "Processed files successfully",
            "files": processed_files
        }),
        headers={"Content-Type": "application/json"}
    )
