import boto3
import json
import zipfile
import os
import time
import argparse
import urllib.request

def deploy_aws_infrastructure(bucket_name, region, domain=None, custom_labels_arn=None):
    """
    Deploys the Woods-Net AWS infrastructure:
    1. S3 Bucket for images
    2. S3 Bucket for Static Website Hosting (Web Portal)
    3. IAM Role for Lambda
    4. Lambda Functions (GenerateUploadUrl, ListImages)
    5. HTTP API Gateway
    6. (Optional) Custom Domain via Route 53, ACM, and CloudFront
    """
    print(f"Starting deployment in region {region}...")
    
    # Initialize boto3 clients
    s3_client = boto3.client('s3', region_name=region)
    iam_client = boto3.client('iam', region_name=region)
    lambda_client = boto3.client('lambda', region_name=region)
    apigw_client = boto3.client('apigatewayv2', region_name=region)
    acm_client = boto3.client('acm', region_name='us-east-1') # CloudFront certs MUST be in us-east-1
    route53_client = boto3.client('route53')
    cloudfront_client = boto3.client('cloudfront')
    dynamodb_client = boto3.client('dynamodb', region_name=region)
    sns_client = boto3.client('sns', region_name=region)
    
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    print(f"Target AWS Account ID: {account_id}")

    # ==========================================
    # 1. Create S3 Bucket
    # ==========================================
    print(f"\n[1] Creating S3 Bucket: {bucket_name}")
    try:
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        
        # Configure bucket CORS to allow browser uploads if we later build a pure frontend
        s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration={
                'CORSRules': [
                    {
                        'AllowedHeaders': ['*'],
                        'AllowedMethods': ['PUT', 'POST', 'GET'],
                        'AllowedOrigins': ['*'],
                        'MaxAgeSeconds': 3000
                    }
                ]
            }
        )
        print("    -> Bucket created and CORS configured.")
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print("    -> Bucket already exists and is owned by you.")
    except Exception as e:
        print(f"    -> Error creating bucket: {e}")
        return

    # ==========================================
    # 1.5 Create S3 Bucket (Web Portal)
    # ==========================================
    portal_bucket = f"{bucket_name}-portal"
    print(f"\n[1.5] Creating S3 Portal Bucket: {portal_bucket}")
    try:
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=portal_bucket)
        else:
            s3_client.create_bucket(
                Bucket=portal_bucket,
                CreateBucketConfiguration={'LocationConstraint': region}
            )

        # Enable Static Website Configuration
        s3_client.put_bucket_website(
            Bucket=portal_bucket,
            WebsiteConfiguration={
                'ErrorDocument': {'Key': 'index.html'},
                'IndexDocument': {'Suffix': 'index.html'}
            }
        )

        # Disable Block Public Access to allow the bucket policy
        s3_client.put_public_access_block(
            Bucket=portal_bucket,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )
        
        # Apply Public Read Policy
        bucket_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{portal_bucket}/*"
                }
            ]
        }
        s3_client.put_bucket_policy(
            Bucket=portal_bucket,
            Policy=json.dumps(bucket_policy)
        )
        print("    -> Portal bucket created, configured for hosting, and made public.")
    except Exception as e:
         print(f"    -> Error configuring portal bucket: {e}")
         # We continue anyway, so the API still deploys

    # ==========================================
    # 1.8 Create DynamoDB Table
    # ==========================================
    table_name = 'WoodsNetImageTags'
    print(f"\n[1.8] Creating DynamoDB Table: {table_name}")
    try:
        dynamodb_client.create_table(
            TableName=table_name,
            KeySchema=[{'AttributeName': 'ImageKey', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'ImageKey', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        print("    -> Waiting for table to be active...")
        dynamodb_client.get_waiter('table_exists').wait(TableName=table_name)
        print("    -> DynamoDB Table created.")
    except dynamodb_client.exceptions.ResourceInUseException:
        print("    -> DynamoDB Table already exists.")

    # ==========================================
    # 1.9 Create SNS Topic for Security Alerts
    # ==========================================
    topic_name = 'WoodsNetSecurityAlerts'
    print(f"\n[1.9] Creating SNS Topic: {topic_name}")
    sns_topic_arn = sns_client.create_topic(Name=topic_name)['TopicArn']
    print(f"    -> SNS Topic created: {sns_topic_arn}")

    # ==========================================
    # 2. Create IAM Role for Lambda
    # ==========================================
    role_name = 'WoodsNetLambdaS3Role'
    print(f"\n[2] Creating IAM Role: {role_name}")
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    try:
         iam_client.create_role(
             RoleName=role_name,
             AssumeRolePolicyDocument=json.dumps(assume_role_policy)
         )
         print("    -> IAM Role created.")
    except iam_client.exceptions.EntityAlreadyExistsException:
         print("    -> IAM Role already exists.")
         
    # Attach S3 Permissions to the Role
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                         "s3:PutObject",
                         "s3:GetObject",
                         "s3:DeleteObject"
                ],
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            },
            {
                 "Effect": "Allow",
                 "Action": [
                      "logs:CreateLogGroup",
                      "logs:CreateLogStream",
                      "logs:PutLogEvents"
                 ],
                 "Resource": "arn:aws:logs:*:*:*"
             },
             {
                 "Effect": "Allow",
                 "Action": ["rekognition:DetectLabels"],
                 "Resource": "*"
             },
             {
                 "Effect": "Allow",
                 "Action": ["dynamodb:PutItem", "dynamodb:Scan", "dynamodb:GetItem", "dynamodb:BatchGetItem"],
                 "Resource": f"arn:aws:dynamodb:{region}:{account_id}:table/{table_name}"
             },
             {
                 "Effect": "Allow",
                 "Action": ["sns:Publish"],
                 "Resource": sns_topic_arn
             }
        ]
    }
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName='WoodsNetS3AccessPolicy',
        PolicyDocument=json.dumps(inline_policy)
    )
    print("    -> Attached S3 & CloudWatch Logs permissions.")
    
    # Wait for IAM role propagation
    print("    -> Waiting 10s for IAM role to propagate...")
    time.sleep(10)

    # ==========================================
    # 3. Zip and Deploy Lambda Functions
    # ==========================================
    upload_func_name = 'WoodsNetGenerateUploadUrl'
    list_func_name = 'WoodsNetListImages'
    manage_func_name = 'WoodsNetManageImage'
    print(f"\n[3] Deploying Lambda Functions")
    
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    
    def deploy_lambda(func_name, code_path, extra_env=None, timeout=10):
        zip_path = f"{func_name}.zip"
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(code_path, arcname='app.py')
            
        with open(zip_path, 'rb') as f:
            zipped_code = f.read()
            
        env_vars = {
            'UPLOAD_BUCKET_NAME': bucket_name,
            'PORTAL_PASSWORD': 'DeerCamp' # Default MVP Password
        }
        if extra_env:
            env_vars.update(extra_env)
            
        try:
            response = lambda_client.create_function(
                FunctionName=func_name,
                Runtime='python3.9',
                Role=role_arn,
                Handler='app.lambda_handler',
                Code={'ZipFile': zipped_code},
                Environment={'Variables': env_vars},
                Timeout=timeout
            )
            print(f"    -> {func_name} created successfully.")
        except lambda_client.exceptions.ResourceConflictException:
            print(f"    -> {func_name} already exists, updating code...")
            lambda_client.update_function_code(
                FunctionName=func_name,
                ZipFile=zipped_code
            )
            lambda_client.update_function_configuration(
                FunctionName=func_name,
                Environment={'Variables': env_vars},
                Timeout=timeout
            )
            print(f"    -> {func_name} updated.")
            
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        return f"arn:aws:lambda:{region}:{account_id}:function:{func_name}"

    upload_lambda_arn = deploy_lambda(upload_func_name, 'lambda_functions/get_presigned_url/app.py')
    list_lambda_arn = deploy_lambda(list_func_name, 'lambda_functions/list_images/app.py')
    manage_lambda_arn = deploy_lambda(manage_func_name, 'lambda_functions/manage_image/app.py')
    timelapse_func_name = 'WoodsNetGenerateTimelapse'
    timelapse_lambda_arn = deploy_lambda(timelapse_func_name, 'lambda_functions/generate_timelapse/app.py', timeout=60)
    
    analyze_func_name = 'WoodsNetAnalyzeImage'
    analyze_env = {'SNS_TOPIC_ARN': sns_topic_arn}
    if custom_labels_arn:
        analyze_env['CUSTOM_LABELS_PROJECT_ARN'] = custom_labels_arn
        
    analyze_lambda_arn = deploy_lambda(analyze_func_name, 'lambda_functions/analyze_image/app.py', extra_env=analyze_env)

    # ==========================================
    # 3.5 Configure S3 Event Trigger for AI Lambda
    # ==========================================
    print(f"\n[3.5] Configuring S3 Event Trigger for {analyze_func_name}")
    try:
        lambda_client.add_permission(
            FunctionName=analyze_func_name,
            StatementId='s3-invoke-permission',
            Action='lambda:InvokeFunction',
            Principal='s3.amazonaws.com',
            SourceArn=f"arn:aws:s3:::{bucket_name}"
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass

    s3_client.put_bucket_notification_configuration(
        Bucket=bucket_name,
        NotificationConfiguration={
            'LambdaFunctionConfigurations': [
                {
                    'LambdaFunctionArn': analyze_lambda_arn,
                    'Events': ['s3:ObjectCreated:Put'],
                    'Filter': {
                        'Key': {
                            'FilterRules': [
                                {'Name': 'prefix', 'Value': 'woods-net/mules/'},
                                {'Name': 'suffix', 'Value': '.avif'}
                            ]
                        }
                    }
                }
            ]
        }
    )
    print("    -> S3 Trigger Configured.")

    # ==========================================
    # 4. Create HTTP API Gateway Routes
    # ==========================================
    api_name = 'WoodsNetAPI'
    print(f"\n[4] Configuring API Gateway: {api_name}")
    
    # Check if API exists
    apis = apigw_client.get_apis()['Items']
    api_id = None
    for api in apis:
        if api['Name'] == api_name:
            api_id = api['ApiId']
            break
            
    if not api_id:
        api_response = apigw_client.create_api(
            Name=api_name,
            ProtocolType='HTTP',
            CorsConfiguration={
                'AllowOrigins': ['*'],
                'AllowMethods': ['GET', 'POST', 'PUT', 'OPTIONS'],
                'AllowHeaders': ['Content-Type', 'Authorization']
            }
        )
        api_id = api_response['ApiId']
        print(f"    -> Created new HTTP API. ID: {api_id}")
    else:
        print(f"    -> Found existing HTTP API. ID: {api_id}")

    def create_api_route(func_name, lambda_arn, route_key):
        # Grant API Gateway permission to invoke Lambda
        try:
            lambda_client.add_permission(
                FunctionName=func_name,
                StatementId='apigateway-invoke-permission',
                Action='lambda:InvokeFunction',
                Principal='apigateway.amazonaws.com',
                SourceArn=f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/*"
            )
        except lambda_client.exceptions.ResourceConflictException:
            pass 

        # Check if integration exists
        integrations = apigw_client.get_integrations(ApiId=api_id)['Items']
        integration_id = None
        for integration in integrations:
            if integration['IntegrationUri'] == lambda_arn:
                 integration_id = integration['IntegrationId']
                 break
                 
        if not integration_id:
            integration_response = apigw_client.create_integration(
                ApiId=api_id,
                IntegrationType='AWS_PROXY',
                IntegrationUri=lambda_arn,
                PayloadFormatVersion='2.0'
            )
            integration_id = integration_response['IntegrationId']
        
        # Create Route
        routes = apigw_client.get_routes(ApiId=api_id)['Items']
        route_exists = False
        for r in routes:
            if r['RouteKey'] == route_key:
                route_exists = True
                break
                
        if not route_exists:
            apigw_client.create_route(
                ApiId=api_id,
                RouteKey=route_key,
                Target=f"integrations/{integration_id}"
            )
            print(f"    -> Created route {route_key}")

    create_api_route(upload_func_name, upload_lambda_arn, 'GET /get-upload-url')
    create_api_route(list_func_name, list_lambda_arn, 'GET /list-images')
    create_api_route(manage_func_name, manage_lambda_arn, 'POST /manage-image')
    create_api_route(timelapse_func_name, timelapse_lambda_arn, 'POST /generate-timelapse')

        
    # Create Stage
    stages = apigw_client.get_stages(ApiId=api_id)['Items']
    stage_exists = False
    for s in stages:
         if s['StageName'] == '$default':
             stage_exists = True
             break
             
    if not stage_exists:
        apigw_client.create_stage(
            ApiId=api_id,
            StageName='$default',
            AutoDeploy=True
        )

    upload_endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/get-upload-url"
    list_endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/list-images"
    base_api = upload_endpoint_url.replace('/get-upload-url', '')
    
    # ==========================================
    # 5. Upload Web Portal Files to S3
    # ==========================================
    print(f"\n[5] Uploading Web Portal Files to {portal_bucket}")
    portal_dir = os.path.join(os.path.dirname(__file__), '..', 'web_portal')
    
    # We dynamically inject the API URL into the app.js before uploading
    if os.path.exists(os.path.join(portal_dir, 'app.js')):
        with open(os.path.join(portal_dir, 'app.js'), 'r') as f:
            app_js_content = f.read()
            
        # Replace the empty API base URL initialization with our live one
        injected_js = app_js_content.replace(
            "let API_BASE_URL = localStorage.getItem('woods_api_url') || '';",
            f"let API_BASE_URL = localStorage.getItem('woods_api_url') || '{base_api}';"
        )
        
        s3_client.put_object(
            Bucket=portal_bucket,
            Key='app.js',
            Body=injected_js.encode('utf-8'),
            ContentType='application/javascript'
        )
        print("    -> Uploaded app.js (Injected with API Route)")

    content_types = {
        'index.html': 'text/html',
        'styles.css': 'text/css'
    }

    for filename in ['index.html', 'styles.css']:
        file_path = os.path.join(portal_dir, filename)
        if os.path.exists(file_path):
             with open(file_path, 'rb') as f:
                 s3_client.put_object(
                     Bucket=portal_bucket,
                     Key=filename,
                     Body=f,
                     ContentType=content_types.get(filename, 'binary/octet-stream')
                 )
             print(f"    -> Uploaded {filename}")
             
    portal_url = f"http://{portal_bucket}.s3-website-{region}.amazonaws.com"
    
    # ==========================================
    # 6. Custom Domain (CloudFront + Route53)
    # ==========================================
    domain = None # Extracted dynamically from kwargs if passed
    if 'domain' in globals() and globals()['domain']:
        pass # Handle this cleanly via function parameters. Let's update the signature implicitly.
        
    def setup_custom_domain(custom_domain):
        print(f"\n[6] Setting up Custom Domain: {custom_domain}")
        
        # 6.1 Find Hosted Zone
        hosted_zones = route53_client.list_hosted_zones_by_name(DNSName=custom_domain)['HostedZones']
        zone_id = None
        for hz in hosted_zones:
            if hz['Name'].startswith(custom_domain):
                zone_id = hz['Id'].split('/')[-1]
                break
                
        if not zone_id:
            print(f"    -> [ERROR] Could not find Route 53 Hosted Zone for {custom_domain}")
            return None
            
        print(f"    -> Found Route 53 Hosted Zone ID: {zone_id}")

        # 6.2 Request ACM Certificate
        print("    -> Requesting ACM SSL Certificate (us-east-1)...")
        cert_response = acm_client.request_certificate(
            DomainName=custom_domain,
            ValidationMethod='DNS',
            SubjectAlternativeNames=[f"*.{custom_domain}"]
        )
        cert_arn = cert_response['CertificateArn']
        
        # 6.3 Wait for Validation Records to be generated
        print("    -> Waiting for DNS validation challenge details...")
        while True:
            desc = acm_client.describe_certificate(CertificateArn=cert_arn)['Certificate']
            if 'DomainValidationOptions' in desc and 'ResourceRecord' in desc['DomainValidationOptions'][0]:
                val_opts = desc['DomainValidationOptions'][0]['ResourceRecord']
                break
            time.sleep(2)
            
        # 6.4 Create Route 53 DNS Validation Record
        print(f"    -> Creating DNS validation record: {val_opts['Name']}")
        route53_client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': val_opts['Name'],
                        'Type': val_opts['Type'],
                        'TTL': 300,
                        'ResourceRecords': [{'Value': val_opts['Value']}]
                    }
                }]
            }
        )
        
        print("    -> Waiting for AWS to validate the certificate (this can take 2-5 minutes)...")
        waiter = acm_client.get_waiter('certificate_validated')
        waiter.wait(CertificateArn=cert_arn)
        print("    -> Certificate Validated!")

        # 6.5 Create CloudFront Distribution
        print("    -> Creating CloudFront CDN Distribution...")
        portal_s3_website_endpoint = f"{portal_bucket}.s3-website-{region}.amazonaws.com"
        
        dist_response = cloudfront_client.create_distribution(
            DistributionConfig={
                'CallerReference': str(time.time()),
                'Aliases': {
                    'Quantity': 1,
                    'Items': [custom_domain]
                },
                'DefaultRootObject': 'index.html',
                'Origins': {
                    'Quantity': 1,
                    'Items': [
                        {
                            'Id': 'S3-PortalBucket',
                            'DomainName': portal_s3_website_endpoint,
                            'CustomOriginConfig': {
                                'HTTPPort': 80,
                                'HTTPSPort': 443,
                                'OriginProtocolPolicy': 'http-only' # S3 website endpoints do not support HTTPS natively back to the origin
                            }
                        }
                    ]
                },
                'DefaultCacheBehavior': {
                    'TargetOriginId': 'S3-PortalBucket',
                    'ViewerProtocolPolicy': 'redirect-to-https',
                    'AllowedMethods': {'Quantity': 2, 'Items': ['HEAD', 'GET'], 'CachedMethods': {'Quantity': 2, 'Items': ['HEAD', 'GET']}},
                    'ForwardedValues': {
                        'QueryString': False,
                        'Cookies': {'Forward': 'none'}
                    },
                    'MinTTL': 0,
                    'DefaultTTL': 86400,
                    'MaxTTL': 31536000
                },
                'Comment': 'Woods-Net Portal CDN',
                'Enabled': True,
                'ViewerCertificate': {
                    'ACMCertificateArn': cert_arn,
                    'SSLSupportMethod': 'sni-only',
                    'MinimumProtocolVersion': 'TLSv1.2_2021'
                }
            }
        )
        
        cf_domain = dist_response['Distribution']['DomainName']
        print(f"    -> CloudFront Distribution created: {cf_domain}")
        
        # 6.6 Create Route 53 A-Alias Record pointing domain to CloudFront
        print(f"    -> Creating Route 53 ALIAS record pointing {custom_domain} to CDN...")
        route53_client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': custom_domain,
                        'Type': 'A',
                        'AliasTarget': {
                            'HostedZoneId': 'Z2FDTNDATAQYW2', # Hosted Zone ID for all CloudFront distributions
                            'DNSName': cf_domain,
                            'EvaluateTargetHealth': False
                        }
                    }
                }]
            }
        )
        print("    -> DNS configured successfully. CDN deployment is propagating globally (takes ~5 mins).")
        return f"https://{custom_domain}"

    # Execution of optional domain logic
    final_portal_url = portal_url
    if domain:
         res = setup_custom_domain(domain)
         if res: final_portal_url = res

    print("\n==========================================")
    print("🚀 API DEPLOYMENT COMPLETE!")
    print(f"✅ Image S3 Bucket: {bucket_name}")
    print(f"✅ Upload API     : {upload_endpoint_url}")
    print(f"✅ List API       : {list_endpoint_url}")
    print(f"🔑 Portal Password: DeerCamp")
    print(f"🌐 PUBLIC PORTAL  : {final_portal_url}")
    print("==========================================")
    print("\nConfiguration for Base Station (faux_base):")
    print(f"AWS_API_URL = '{upload_endpoint_url}'")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Deploy Woods-Net AWS Serverless Backend")
    parser.add_argument('--bucket', required=True, help="Globally unique S3 bucket name")
    parser.add_argument('--region', default='us-east-1', help="AWS Region (default: us-east-1)")
    parser.add_argument('--domain', help="Optional custom domain to map via Route 53 and CloudFront (e.g. mulenet.online)")
    parser.add_argument('--custom-labels-arn', help="Optional AWS Rekognition Custom Labels Model ARN for advanced Buck Age/Score estimation")
    
    args = parser.parse_args()
    deploy_aws_infrastructure(args.bucket, args.region, args.domain, args.custom_labels_arn)
