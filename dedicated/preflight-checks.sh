#!/bin/bash
# Gitpod Dedicated AWS account preflight check

# Variables for each of the required account quotas
MAX_STANDARD_EC2_INSTANCES=256
MAX_CONCURRENT_LAMBDA_EXECUTIONS=1024
MAX_VPCS=4
MAX_EIPS=20

ORANGE='\033[0;33m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'
NO_COLOR='\033[0m'

echo -e "${ORANGE}"
cat << "EOF"
   _____  _  _                      _ 
  / ____|(_)| |                    | |
 | |  __  _ | |_  _ __    ___    __| |
 | | |_ || || __|| '_ \  / _ \  / _` |
 | |__| || || |_ | |_) || (_) || (_| |
  \_____||_| \__|| .__/  \___/  \__,_|
                 | |                  
                 |_|                                  
EOF
echo -e "${NO_COLOR}""${CYAN}""         Always ready-to-code.""${NO_COLOR}"
echo ""
echo -e "${WHITE}""Welcome to the Gitpod Dedicated preflight check.""${NO_COLOR}"

# Check if the AWS CLI is installed
if ! command -v aws &>/dev/null; then
  echo "AWS CLI not found. Please install the AWS CLI and configure your credentials."
  exit 1
fi

# Check if a region is provided as an argument
if [ $# -eq 0 ]; then
  echo "Usage: $0 <REGION>"
  exit 1
fi

REGION="$1"

# Fetch the appropriate quota codes. These are region specific so we can't hard-code them.
EC2_INSTANCES_QUOTA_NAME="Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances"
LAMBDA_CONCURRENT_EXECUTIONS_QUOTA_NAME="Concurrent executions"
VPC_MAX_VPCS_QUOTA_NAME="VPCs per Region"
VPC_MAX_EIPS_QUOTA_NAME="EC2-VPC Elastic IPs"

# Get the quota code for 'Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances'
QCODE_EC2_INSTANCES=$(aws service-quotas list-service-quotas --service-code ec2 --region "$REGION" --query "Quotas[?ServiceName=='Amazon Elastic Compute Cloud (Amazon EC2)' && QuotaName=='$EC2_INSTANCES_QUOTA_NAME'].QuotaCode" --output text)

# Get the quota code for number of concurrent lambda executions
QCODE_LAMBDA_CONCURRENT_EXECUTIONS=$(aws service-quotas list-service-quotas --service-code lambda --region "$REGION" --query "Quotas[?ServiceName=='AWS Lambda' && QuotaName=='$LAMBDA_CONCURRENT_EXECUTIONS_QUOTA_NAME'].QuotaCode" --output text)

# Get the quota code for the max number of VPCs in the region
QCODE_VPC_MAX_VPCS=$(aws service-quotas list-service-quotas --service-code vpc --region "$REGION" --query "Quotas[?ServiceName=='Amazon Virtual Private Cloud (Amazon VPC)' && QuotaName=='$VPC_MAX_VPCS_QUOTA_NAME'].QuotaCode" --output text)

# Get the quota code for the maximum number of elastic IPs in a VPC
QCODE_VPC_MAX_EIPS=$(aws service-quotas list-service-quotas --service-code ec2 --region "$REGION" --query "Quotas[?ServiceName=='Amazon Elastic Compute Cloud (Amazon EC2)' && QuotaName=='$VPC_MAX_EIPS_QUOTA_NAME'].QuotaCode" --output text)

# Function to check resource quota
function check_resource_quota() {
  local resource="$1"
  local quota="$2"
  local quota_name="$3"
  local desired_quota="$4"

  float_quota=$(aws service-quotas get-service-quota --service-code "$resource" --quota-code "$quota" --region "$REGION" --query "Quota.Value" --output text 2>/dev/null)

  actual_quota=$(printf %.0f "$float_quota")

  if [ "$actual_quota" -ge "$desired_quota" ]; then
    echo -e "✅  $resource - $quota_name\nQuota: $actual_quota (Minimum Required: $desired_quota)"
  else
    echo -e "❌  $resource - $quota_name\nQuota: $actual_quota (Minimum Required: $desired_quota)"
    quota_increase_requests+=("$quota_name")
  fi

  echo ""
}

echo "Checking your AWS account quotas for region $REGION..."
echo ""

# Verify resource quotas
quota_increase_requests=()
check_resource_quota "ec2" "$QCODE_EC2_INSTANCES" "$EC2_INSTANCES_QUOTA_NAME" "$MAX_STANDARD_EC2_INSTANCES"
check_resource_quota "lambda" "$QCODE_LAMBDA_CONCURRENT_EXECUTIONS" "$LAMBDA_CONCURRENT_EXECUTIONS_QUOTA_NAME" "$MAX_CONCURRENT_LAMBDA_EXECUTIONS"
check_resource_quota "vpc" "$QCODE_VPC_MAX_VPCS" "$VPC_MAX_VPCS_QUOTA_NAME" "$MAX_VPCS"
check_resource_quota "ec2" "$QCODE_VPC_MAX_EIPS" "$VPC_MAX_EIPS_QUOTA_NAME" "$MAX_EIPS"

# Check if any quota increase requests need to be submitted
if [ ${#quota_increase_requests[@]} -eq 0 ]; then
  echo "All quotas meet the minimum requirements. No quota increase requests need to be submitted."
else
  echo "The following quotas require an increase:"
  for quota_name in "${quota_increase_requests[@]}"; do
    echo "- $quota_name"
  done
  echo ""
  read -r -p "Would you like to submit increase requests for these quotas? (Y/N) " response
  if [ "$response" == "Y" ] || [ "$response" == "y" ]; then
    for quota_name in "${quota_increase_requests[@]}"; do
      case "$quota_name" in
        "$EC2_INSTANCES_QUOTA_NAME")
          quota="$QCODE_EC2_INSTANCES"
          service_code="ec2"
          desired_quota="$MAX_STANDARD_EC2_INSTANCES"
          ;;
        "$LAMBDA_CONCURRENT_EXECUTIONS_QUOTA_NAME")
          quota="$QCODE_LAMBDA_CONCURRENT_EXECUTIONS"
          service_code="lambda"
          desired_quota="$MAX_CONCURRENT_LAMBDA_EXECUTIONS"
          ;;
        "$VPC_MAX_VPCS_QUOTA_NAME")
          quota="$QCODE_VPC_MAX_VPCS"
          service_code="vpc"
          desired_quota="$MAX_VPCS"
          ;;
        "$VPC_MAX_EIPS_QUOTA_NAME")
          quota="$QCODE_VPC_MAX_EIPS"
          service_code="ec2"
          desired_quota="$MAX_EIPS"
          ;;
      esac

      # Check if a quota increase request has already been submitted for the quota
      if aws service-quotas list-requested-service-quota-change-history --service-code "$service_code" --region "$REGION" --query "RequestedQuotas[?QuotaCode=='$quota' && (Status=='PENDING' || Status=='CASE_OPENED')]" --output text | grep -q "$quota_name"; then
        echo -e "A quota increase request for $quota_name is already pending.\nPlease wait for the request to be approved before submitting another request."
      else
        # Submit the quota increase request
        aws service-quotas request-service-quota-increase --service-code "$service_code" --region "$REGION" --quota-code "$quota" --desired-value "$desired_quota" > /dev/null
        echo "Quota increase request for $quota_name submitted. Please allow up to 24 hours for it to be approved."
      fi
    done
  else
    echo "No quota increase requests were submitted."
  fi
fi
