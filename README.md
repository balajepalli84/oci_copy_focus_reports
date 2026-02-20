# **Automating the Export of OCI FinOps Open Cost and Usage Specification (FOCUS) Reports to Object Storage**


#### In Oracle Cloud Infrastructure (OCI), cost and usage reports provide essential insights into your cloud spending. Today, you can view and manually download these reports. However, this process can become cumbersome if you need to build a custom dashboard using Analytics services like OAC or connect to third-party services that provide a centralized cost view for all your resources across multiple cloud environments.

#### In this blog post, we will show you how to automate the export of your Cost Management data to an Object Storage bucket in your tenancy. This approach streamlines data access and enables integration with other systems, custom data enrichment, and analysis in external tools like dashboards or financial systems, offering enhanced insights and simplified reporting.

#### FOCUS is a new open-source cloud billing data specification that provides consistency and standardization to simplify cloud cost reporting and analysis across multiple sources. Refer to this blog post for additional information. 

---

## **Prerequisites**

* Object Storage Bucket: Create a bucket in OCI Object Storage (example 'Cost_Usage_Reports') to store the cost and usage reports. 
* Dynamic Groups:

  * Create a dynamic group (like 'dg-fn-copy-CUR-reports') for the function to copy files to Object Storage –
    'ALL {resource.type = 'fnfunc', resource.compartment.id = 'ocid1.compartment.oc1..xxx'}' 

---

## **Creating Automated Daily Reports**

To automate the daily copying of FOCUS (Cost and Usage Reports), we will set up an OCI Function that performs this task daily. 

### **Step 1 – Create an OCI Function to Copy FOCUS Reports to Object Storage**

1. Set up an OCI Function that will be responsible for copying the FOCUS reports to your Object Storage bucket. Refer to this guide for detailed steps to create an OCI Function. 
2. Use the following code in your function: 

```
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

            # Handle zip files
            if zipfile.is_zipfile(local_file_path):
                with zipfile.ZipFile(local_file_path, 'r') as zip_ref:
                    for extracted_name in zip_ref.namelist():
                        extracted_path = os.path.join(destination_path, extracted_name)
                        if os.path.isdir(extracted_path):
                            continue
                        os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
                        zip_ref.extract(extracted_name, destination_path)
                        dest_object_path = os.path.join(os.path.dirname(source_object_path), extracted_name)
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
```
---

### **Step 2 – Schedule the Function invocation using Resource Scheduler**

Configure the Resource Scheduler to invoke this function daily. Follow instructions in this blog post to set up a daily job. 

---

### **Step 3 – Set Up Required Policies**

Using the Dynamic Groups created earlier, ensure you have these policies in place: 

* **Policy 1 – Allow the Resource Scheduler to invoke the function.**

```
  Allow any-user to manage functions-family in Tenancy
    where all {request.principal.type='resourceschedule', request.principal.id='ocid1.resourceschedule.oc1.iad.xxxxx'}
```

* **Policy 2 – Permit the function to access and write to Object Storage buckets.**

```
  Allow dynamic-group dg-fn-copy-CUR-reports to manage in compartment <your-compartment>
  define tenancy usage-report as ocid1.tenancy.oc1..aaaaaaaaned4fkpkisbwjlr56u7cj63lf3wffbilvqknstgtvzub7vhqkggq
  endorse dynamic-group dg-fn-copy-CUR-reports to read objects in tenancy usage-report
  Allow dynamic-group dg-fn-copy-CUR-reports to inspect compartments in tenancy
  Allow dynamic-group dg-fn-copy-CUR-reports to inspect tenancies in tenancy
```

**Note:** For this example, broad access permissions were used. For a real production environment, use fine-grained permissions. 

---

Once these configurations are complete, the Resource Scheduler will automatically trigger the function each day at the scheduled time, copying the FOCUS reports to your designated Object Storage bucket. 

