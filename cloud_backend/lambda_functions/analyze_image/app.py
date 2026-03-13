import json
import boto3
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import io
from PIL import Image, ExifTags
from pillow_heif import register_heif_opener

register_heif_opener()

rekognition = boto3.client('rekognition')
dynamodb = boto3.client('dynamodb')
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

def fetch_weather_data(lat, lng):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,wind_speed_10m,surface_pressure&daily=moon_phase,moon_illumination&timezone=auto"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WoodsNet/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            current = data.get('current', {})
            daily = data.get('daily', {})
            
            return {
                'temperature_c': current.get('temperature_2m'),
                'wind_kph': current.get('wind_speed_10m'),
                'pressure_hpa': current.get('surface_pressure'),
                'moon_phase': daily.get('moon_phase', [0])[0] if daily.get('moon_phase') else 0
            }
    except Exception as e:
        print(f"Failed to fetch weather: {e}")
        return None

def lambda_handler(event, context):
    """
    Triggered by S3 ObjectCreated events.
    Passes the new image to AWS Rekognition for label detection.
    Writes the resulting tags and object counts to DynamoDB.
    """
    
    # Target DynamoDB table name
    table_name = os.environ.get('DYNAMODB_TABLE_NAME', 'WoodsNetImageTags')
    
    try:
        # 1. Flatten Event Structure (Handle SQS wrapping)
        s3_records = []
        for raw_record in event.get('Records', []):
            if 'body' in raw_record:
                # SQS Wrapper
                try:
                    body_json = json.loads(raw_record['body'])
                    s3_records.extend(body_json.get('Records', []))
                except Exception as e:
                    print(f"Failed to decode SQS JSON wrapper: {e}")
            elif 's3' in raw_record:
                s3_records.append(raw_record)
                
        # 2. Process flattened records
        for record in s3_records:
            bucket = record['s3']['bucket']['name']
            key = urllib.parse.unquote_plus(record['s3']['object']['key'])
            print(f"RAW PAYLOAD KEY EVALUATION: {key}")
            
            # We only care about .avif images in the cameras directory.
            # Avoid processing the _config mappings file or UI assets if any.
            if not (key.startswith('woods-net/cameras/') and key.lower().endswith('.avif')):
                print(f"Skipping analysis for non-capture file: {key}")
                continue
                
            parts = key.split('/')
            mule_id = parts[2] if len(parts) >= 3 else None
            
            weather_data = None
            if mule_id:
                try:
                    mapping_obj = s3_client.get_object(Bucket=bucket, Key='_config/camera_mappings.json')
                    mule_mappings = json.loads(mapping_obj['Body'].read().decode('utf-8'))
                    mule_info = mule_mappings.get(mule_id)
                    if isinstance(mule_info, dict) and 'lat' in mule_info and 'lng' in mule_info:
                        weather_data = fetch_weather_data(mule_info['lat'], mule_info['lng'])
                        print(f"Fetched weather data for {key}: {weather_data}")
                except Exception as e:
                    print(f"Could not load mule mappings or weather info: {e}")
                
            print(f"Analyzing Image: s3://{bucket}/{key}")
            
            # Call AWS Rekognition
            # We use a relatively high confidence threshold (75%) to avoid false positives (like a log looking like a bear).
            
            # --- START AVIF CONVERSION LOGIC ---
            # Rekognition doesn't natively support AVIF, so we must download and convert to JPEG in-memory.
            print(f"Downloading and converting AVIF to JPEG for Rekognition...")
            img_obj = s3_client.get_object(Bucket=bucket, Key=key)
            img_bytes = img_obj['Body'].read()
            image = Image.open(io.BytesIO(img_bytes))
            
            # Extract EXIF early while we have the raw opened AVIF Pillow object
            exif = image.getexif()
            capture_time = None
            if exif:
                # DateTimeOriginal (36867) is usually nested within the ExifOffset IFD (0x8769)
                exif_time_str = None
                ifd = exif.get_ifd(0x8769)
                if ifd and 36867 in ifd:
                    exif_time_str = ifd[36867]
                elif 306 in exif: # Fallback to standard DateTime
                    exif_time_str = exif[306]
                    
                if exif_time_str:
                    try:
                        dt = datetime.strptime(exif_time_str, '%Y:%m:%d %H:%M:%S')
                        capture_time = dt.isoformat() + "Z"
                    except ValueError:
                        pass
            
            # Convert to JPEG bytes for Rekognition
            if image.mode != "RGB":
                image = image.convert("RGB")
            jpeg_io = io.BytesIO()
            image.save(jpeg_io, format="JPEG", quality=85)
            jpeg_bytes = jpeg_io.getvalue()
            
            response = rekognition.detect_labels(
                Image={'Bytes': jpeg_bytes},
                MaxLabels=15,
                MinConfidence=80
            )
            # --- END AVIF CONVERSION LOGIC ---
            labels = response.get('Labels', [])
            
            # Define the only Categories we care about from AWS
            allowed_categories = [
                'Animals and Pets',
                'Person Description' # (Face, Male, Adult, Person)
            ]
            
            # First pass: Look for specific flags
            has_antlers = any(l['Name'] in ['Antler', 'Horn'] for l in labels)
            has_person_parts = False # Tracks if we found *any* human attributes
            has_animals = False
            has_buck = False
            has_doe = False
            detected_tags = {}
            
            for label in labels:
                label_name = label['Name']
                
                # Check if this tag belongs to an allowed category
                label_categories = [cat['Name'] for cat in label.get('Categories', [])]
                label_name = label.get('Name', 'Unknown')
                
                if not any(c in allowed_categories for c in label_categories):
                    continue # Ignore Weather, Plants, Furniture, Scenery, etc.
                    
                # We're in an allowed category! Let's handle specific rules.
                
                # --- Human Handling ---
                if 'Person Description' in label_categories or label_name in ['Person', 'Human', 'People']:
                    has_person_parts = True
                    has_animals = True # Set flag so it's not filtered out as 'empty'
                    continue # We don't want to save "Face", "Male", "Shirt", we just want "Person" eventually
                
                # --- Animal Handling ---
                if 'Animals and Pets' in label_categories:
                    if label_name not in ['Antler', 'Horn']:
                        has_animals = True
                        
                    # Skip recording generic tags or standalone antler parts if we can avoid it, but we'll prune generics later
                    if label_name in ['Animal', 'Wildlife', 'Mammal', 'Antler', 'Horn']:
                        continue 
                        
                    # Normalize errant ML labels to target wildlife group
                    normalization_map = {
                        'Kangaroo': 'Deer',
                        'Antelope': 'Deer',
                        'Elk': 'Deer',
                        'Pig': 'Deer',
                        'Cow': 'Deer',
                        'Impala': 'Deer',
                        'Moose': 'Deer',
                        'Reindeer': 'Deer',
                        'Cattle': 'Deer'
                    }
                    if label_name in normalization_map:
                        label_name = normalization_map[label_name]

                    # Custom logic for Deer sexing based on user request
                    if label_name == 'Deer':
                        if has_antlers:
                            label_name = 'Antlered Buck'
                            has_buck = True
                        else:
                            label_name = 'Doe/Young'
                            has_doe = True
                    else:
                        label_name = 'Other Wildlife'
                
                # All detected tags are strictly tracked as Boolean '1' flags without mathematical volume.
                detected_tags[label_name] = 1
            
            # --- Final Tag Consolidation ---
            # If we saw ANY human attributes (Face, Male, Shirt, etc), we consolidate them all into exactly one "Person" tag.
            if has_person_parts:
                # We don't care about counting people, just if one was broadly detected.
                detected_tags['Person'] = 1
                
            # If no specific tags were found, but we flagged "Animal", ensure we at least record that.
            if has_animals and not detected_tags:
                detected_tags["Other Wildlife"] = 1
                
            # Second Pass: AWS Rekognition Custom Labels (Target Buck / Age Estimation)
            # This only runs if the user has trained a specific model and provided the ARN, AND a buck was detected.
            custom_model_arn = os.environ.get('CUSTOM_LABELS_PROJECT_ARN')
            if custom_model_arn and has_buck:
                try:
                    custom_response = rekognition.detect_custom_labels(
                        ProjectVersionArn=custom_model_arn,
                        Image={'Bytes': jpeg_bytes},
                        MinConfidence=60
                    )
                    for custom_label in custom_response.get('CustomLabels', []):
                        # Use an emoji prefix to visually separate AI-Trained tags from standard AWS tags on the UI
                        detected_tags[f"🎯 {custom_label['Name']}"] = 1
                except Exception as e:
                    print(f"Skipping custom labels analysis (model might be turned off): {e}")
                
            print(f"Detected Tags for {key}: {detected_tags}")
            
            # Convert dictionary into DynamoDB AttributeValue format
            # { 'Deer': {'N': '2'}, 'Raccoon': {'N': '1'} }
            dynamo_tags = {k: {'N': str(v)} for k, v in detected_tags.items()}
            
            # EXIF extraction was handled at the beginning of the script.

            # Store in DynamoDB
            item = {
                'ImageKey': {'S': key},
                'HasAnimals': {'BOOL': has_animals},
                'Tags': {'M': dynamo_tags}
            }
            if capture_time:
                item['CaptureTime'] = {'S': capture_time}
            
            if weather_data:
                t = weather_data.get('temperature_c')
                w = weather_data.get('wind_kph')
                p = weather_data.get('pressure_hpa')
                m = weather_data.get('moon_phase')
                
                # DynamoDB numbers must be passed as strings
                item['Weather'] = {
                    'M': {
                        'temp': {'N': str(t) if t is not None else '0'},
                        'wind': {'N': str(w) if w is not None else '0'},
                        'pressure': {'N': str(p) if p is not None else '0'},
                        'moon': {'N': str(m) if m is not None else '0'}
                    }
                }
                
            dynamodb.put_item(
                TableName=table_name,
                Item=item
            )
            
            # Update Mule Hardware State in DynamoDB for the Live Dashboard
            state_item = {
                'ImageKey': {'S': f"MULE_STATE#{mule_id}"},
                'LastHeartbeat': {'S': datetime.now(timezone.utc).isoformat()},
                # Mocking hardware telemetry for the MVP dashboard
                'Battery': {'N': '92'}, 
                'Signal': {'N': '-68'},
                'PowerLevel': {'S': 'PL3_ACTIVE'}
            }
            dynamodb.put_item(
                TableName=table_name,
                Item=state_item
            )
            
            print(f"Successfully saved tags and state to DynamoDB for {key}")
            
            # Trigger targeted SNS Alerts utilizing the WoodsNetSubscribers Routing Matrix
            try:
                subscribers_response = dynamodb.scan(TableName='WoodsNetSubscribers')
                subscribers = subscribers_response.get('Items', [])
                
                # Determine which high-priority tags the AI actually flagged
                active_ai_tags = []
                if has_person_parts:
                    active_ai_tags.append('Person')
                if has_buck:
                    active_ai_tags.append('Antlered Buck')
                if has_doe:
                    active_ai_tags.append('Doe/Young')
                
                if active_ai_tags:
                    # Generate a secure 7-day presigned URL for the SMS payload
                    try:
                        alert_url = s3_client.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': bucket, 'Key': key},
                            ExpiresIn=604800
                        )
                    except Exception as e:
                        alert_url = f"s3://{bucket}/{key}"
                        
                    for sub in subscribers:
                        # Verify the user is globally active
                        if not sub.get('IsActive', {}).get('BOOL', True):
                            continue
                        
                        # Extract the user's specific routing rules for this particular camera
                        routing_matrix = sub.get('RoutingMatrix', {}).get('M', {})
                        camera_id = mule_id if mule_id else 'Unknown'
                        mule_routing = routing_matrix.get(camera_id, {}).get('L', [])
                        
                        user_requested_tags = [t.get('S') for t in mule_routing if 'S' in t]
                        
                        # See if the AI tags intersect with the User's requested tags
                        matched_tags = list(set(active_ai_tags) & set(user_requested_tags))
                        
                        if matched_tags:
                            sms_number = sub.get('ContactMethods', {}).get('M', {}).get('sms', {}).get('S', '')
                            # AWS SNS requires E.164 format (e.g. +15551234567)
                            if sms_number and sms_number.startswith('+'):
                                tag_str = " & ".join(matched_tags).upper()
                                msg_body = f"🚨 Woods-Net Alert 🚨\n{tag_str} detected at {camera_id}!\n\nView Image:\n{alert_url}"
                                
                                try:
                                    # Dispatch personalized SMS directly to the user's phone
                                    sns_client.publish(
                                        PhoneNumber=sms_number,
                                        Message=msg_body
                                    )
                                    sub_name = sub.get('Name', {}).get('S', 'Unknown')
                                    print(f"Targeted SMS delivered to {sub_name} ({sms_number}) for {camera_id}")
                                except Exception as e:
                                    print(f"Failed to publish direct SMS to {sms_number}: {e}")
            except Exception as e:
                print(f"Error processing dynamic subscriber alerts: {e}")
            
    except Exception as e:
        print(f"Error processing S3 Event: {e}")
        # We don't necessarily want to fail the lambda and retry indefinitely if an image is corrupted.
        # But depending on the queue configuration, raising the exception might be desired.
        raise e
        
    return {
        'statusCode': 200,
        'body': json.dumps('Analysis Complete')
    }
