#!/usr/bin/env python3

# To install boto3, run: pip install boto3
import boto3
import json
import os
import time
import argparse
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
from collections import defaultdict
from typing import Dict, List, Set, Tuple

# Constants for file names
GET_PARAMETER_FILE = 'get_parameter_events.json'
RUN_INSTANCES_FILE = 'run_instances_events.json'
ASSUME_ROLE_FILE = 'assume_role_events.json'

# Event types to fetch
EVENT_TYPES = {
    'GetParameter': GET_PARAMETER_FILE,
    'RunInstances': RUN_INSTANCES_FILE,
    'AssumeRole': ASSUME_ROLE_FILE
}

def parse_arguments():
    """
    Parse command line arguments.
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Fetch CloudTrail events for specific event types')
    parser.add_argument('--days', type=int, default=90,
                      help='Number of days to look back for events (default: 90)')
    return parser.parse_args()

def create_cloudtrail_client():
    """
    Create and return a CloudTrail client using the AWS_REGION environment variable.
    Raises an exception if AWS_REGION is not set.
    """
    aws_region = os.environ.get('AWS_REGION')
    if not aws_region:
        raise ValueError("AWS_REGION environment variable is not set. Please set it before running the script.")
    
    try:
        return boto3.client('cloudtrail', region_name=aws_region)
    except Exception as e:
        print(f"Error creating CloudTrail client in region {aws_region}: {str(e)}")
        raise

def fetch_events(cloudtrail_client, event_name, start_time, end_time):
    """
    Fetch CloudTrail events for a specific event name with pagination and rate limit handling.
    
    Args:
        cloudtrail_client: Boto3 CloudTrail client
        event_name: Name of the event to fetch
        start_time: Start time for the query
        end_time: End time for the query
    
    Returns:
        List of events
    """
    events = []
    next_token = None
    page_number = 1
    
    while True:
        try:
            # Prepare the lookup attributes
            lookup_attributes = [{
                'AttributeKey': 'EventName',
                'AttributeValue': event_name
            }]
            
            # Prepare the parameters for lookup_events
            params = {
                'LookupAttributes': lookup_attributes,
                'StartTime': start_time,
                'EndTime': end_time,
                'MaxResults': 50  # Maximum allowed by AWS
            }
            
            if next_token:
                params['NextToken'] = next_token
            
            print(f"Fetching {event_name} events (Page {page_number})...")
            response = cloudtrail_client.lookup_events(**params)
            
            if 'Events' in response:
                events.extend(response['Events'])
                print(f"Retrieved {len(response['Events'])} {event_name} events on page {page_number}")
            
            # Check if there are more events to fetch
            next_token = response.get('NextToken')
            if not next_token:
                print(f"Completed fetching {event_name} events. Total pages: {page_number}")
                break
            
            page_number += 1
                
        except ClientError as e:
            if e.response['Error']['Code'] == 'ThrottlingException':
                print(f"Rate limit exceeded on page {page_number}. Waiting for 5 seconds...")
                time.sleep(5)
                continue
            else:
                print(f"Error fetching {event_name} events on page {page_number}: {str(e)}")
                raise
        except Exception as e:
            print(f"Unexpected error fetching {event_name} events on page {page_number}: {str(e)}")
            raise
    
    return events

def save_events_to_file(events, filename):
    """
    Save events to a JSON file.
    
    Args:
        events: List of events to save
        filename: Name of the file to save to
    """
    try:
        with open(filename, 'w') as f:
            json.dump(events, f, indent=2, default=str)
        print(f"Successfully saved {len(events)} events to {filename}")
    except Exception as e:
        print(f"Error saving events to {filename}: {str(e)}")
        raise


def load_json_file(filename: str) -> List[dict]:
    """Load and parse a JSON file."""
    with open(filename, 'r') as f:
        return json.load(f)

def extract_run_instances_data(events: List[dict]) -> Dict[str, Tuple[str, str]]:
    """
    Extract instance ID, profile ARN, and environment ID from RunInstances events.
    Returns a dict mapping instance ID to (profile_arn, environment_id)
    """
    instance_data = {}
    
    for event in events:
        try:
            # Parse the CloudTrail event JSON string
            cloudtrail_event = json.loads(event['CloudTrailEvent'])
            
            # Defensive check for response elements
            response_elements = cloudtrail_event.get('responseElements')
            if not response_elements:
                continue
                
            instances_set = response_elements.get('instancesSet')
            if not instances_set:
                continue
                
            items = instances_set.get('items')
            if not items or not items[0]:
                continue
                
            instance = items[0]
            
            # Extract required fields using exact paths
            instance_id = instance.get('instanceId')
            if not instance_id:
                continue
                
            iam_profile = instance.get('iamInstanceProfile')
            if not iam_profile:
                continue
                
            profile_arn = iam_profile.get('arn')
            profile_id = iam_profile.get('id')
            
            # Get environment ID from tags
            tag_set = instance.get('tagSet', {})
            tags = tag_set.get('items', [])
            environment_id = next((tag['value'] for tag in tags if tag.get('key') == 'gitpod.dev/environment-id'), None)
            
            if instance_id and profile_arn and environment_id:
                instance_data[instance_id] = (profile_arn, environment_id)
                print(f"Found instance {instance_id} with profile {profile_arn} and environment {environment_id}")
                
        except (KeyError, json.JSONDecodeError) as e:
            print(f"Error processing RunInstances event: {str(e)}")
            print(f"Event ID: {event.get('EventId', 'unknown')}")
            continue
    
    return instance_data

def find_assume_role_events(events: List[dict], profile_arns: Set[str]) -> Dict[str, str]:
    """
    Find AssumeRole events that match the given profile ARNs.
    Returns a dict mapping session ID to access key ID
    """
    assume_role_data = {}
    
    for event in events:
        try:
            cloudtrail_event = json.loads(event['CloudTrailEvent'])
            
            # Check if this is an AssumeRole event for one of our profiles
            if cloudtrail_event['eventName'] == 'AssumeRole':
                role_arn = cloudtrail_event['requestParameters']['roleArn']
                if role_arn in profile_arns:
                    session_id = cloudtrail_event['responseElements']['credentials']['sessionToken']
                    access_key_id = cloudtrail_event['responseElements']['credentials']['accessKeyId']
                    assume_role_data[session_id] = access_key_id
                    
        except (KeyError, json.JSONDecodeError) as e:
            print(f"Error processing AssumeRole event: {str(e)}")
            continue
    
    return assume_role_data

def find_get_parameter_events(events: List[dict], environment_ids: Set[str]) -> Dict[str, List[str]]:
    """
    Find GetParameter events that match the given environment IDs.
    Returns a dict mapping environment ID to list of parameter names
    """
    parameter_data = defaultdict(list)
    
    for event in events:
        try:
            cloudtrail_event = json.loads(event['CloudTrailEvent'])
            
            if cloudtrail_event['eventName'] == 'GetParameter':
                parameter_name = cloudtrail_event['requestParameters']['name']
                
                # Check if parameter name contains any of our environment IDs
                for env_id in environment_ids:
                    if env_id in parameter_name:
                        parameter_data[env_id].append(parameter_name)
                        
        except (KeyError, json.JSONDecodeError) as e:
            print(f"Error processing GetParameter event: {str(e)}")
            continue
    
    return parameter_data

def analyze():
     # Load all event files
    print("Loading event files...")
    run_instances_events = load_json_file('run_instances_events.json')
    assume_role_events = load_json_file('assume_role_events.json')
    get_parameter_events = load_json_file('get_parameter_events.json')
    
    # Extract RunInstances data
    print("\nAnalyzing RunInstances events...")
    instance_data = extract_run_instances_data(run_instances_events)
    print(f"Found {len(instance_data)} instances with profile ARNs and environment IDs")
    
    # Get unique profile ARNs and environment IDs
    profile_arns = {data[0] for data in instance_data.values()}
    environment_ids = {data[1] for data in instance_data.values()}
    
    # Find matching AssumeRole events
    print("\nAnalyzing AssumeRole events...")
    assume_role_data = find_assume_role_events(assume_role_events, profile_arns)
    print(f"Found {len(assume_role_data)} matching AssumeRole events")
    
    # Find matching GetParameter events
    print("\nAnalyzing GetParameter events...")
    parameter_data = find_get_parameter_events(get_parameter_events, environment_ids)
    print(f"Found {len(parameter_data)} environment IDs with matching GetParameter events")
    
    # Print only instances with mismatched environment IDs
    print(f"ANALYZING VULNERABILITY USAGE")
    print("\nThe following instances have accessed GetParameter which does not match their environment ID:")
    print("=========================================")
    count = 0
    for instance_id, (profile_arn, environment_id) in instance_data.items():
        # Check if there are any GetParameter calls for this instance
        if environment_id in parameter_data:
            # Get all parameter names for this environment
            param_names = parameter_data[environment_id]
            # Check if any parameter name contains a different environment ID
            has_mismatch = any(env_id in param_name and env_id != environment_id 
                             for param_name in param_names 
                             for env_id in environment_ids)
            if has_mismatch:
                count += 1
                print(f"\nInstance: {instance_id}")
                print(f"Profile ARN: {profile_arn}")
                print(f"Environment ID: {environment_id}")
                print("Mismatched GetParameter calls:")
                for param_name in param_names:
                    print(f"  - {param_name}")
    
    if count == 0:
        print("No instances with mismatched environment IDs found")
        print("")
        print("SECURITY VULNERABILITY HAS NOT BEEN EXPLOITED")
    else:
        print(f"Found {count} instances with mismatched environment IDs. Reach out to Gitpod to help with remediation.")

def main():
    """Main function to orchestrate the CloudTrail event fetching process."""
    # Parse command line arguments
    args = parse_arguments()
    
    # Check if all files already exist
    if all(os.path.exists(filename) for filename in EVENT_TYPES.values()):
        print("All event files already exist. Skipping fetch.")
        analyze()
        return
    
    # Create CloudTrail client
    cloudtrail_client = create_cloudtrail_client()
    
    # Set time range based on command line argument
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=args.days)
    print(f"Fetching events from {start_time} to {end_time} ({args.days} days)")
    
    # Fetch events for each event type
    for event_name, filename in EVENT_TYPES.items():
        if os.path.exists(filename):
            print(f"File {filename} already exists. Skipping {event_name} events.")
            continue
            
        print(f"\nProcessing {event_name} events...")
        events = fetch_events(cloudtrail_client, event_name, start_time, end_time)
        
        if events:
            save_events_to_file(events, filename)
        else:
            print(f"No {event_name} events found in the specified time range.")
            return

    analyze()

if __name__ == "__main__":
    main()
