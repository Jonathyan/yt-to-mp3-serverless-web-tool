#!/bin/bash

# AWS Setup Script voor Sprint 0
# Zorg dat AWS CLI is geïnstalleerd en geconfigureerd

set -e  # Stop bij errors

echo "🚀 AWS Setup voor YouTube naar MP3 Project"
echo "=========================================="

# Variabelen
AWS_REGION=${AWS_REGION:-"eu-west-1"}  # Amsterdam region
PROJECT_NAME="preek-mp3"
BUCKET_NAME="${PROJECT_NAME}-storage-$(date +%s)"  # Unique bucket name
IAM_USER_NAME="${PROJECT_NAME}-developer"
LAMBDA_ROLE_NAME="${PROJECT_NAME}-lambda-role"

# Kleuren voor output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "\n${YELLOW}📍 Regio: ${AWS_REGION}${NC}"

# Stap 1: Maak IAM Developer User
echo -e "\n${GREEN}1. IAM Developer User aanmaken...${NC}"
aws iam create-user --user-name $IAM_USER_NAME 2>/dev/null || echo "User bestaat al"

# Stap 2: Maak en attach developer policy
echo -e "\n${GREEN}2. Developer Policy aanmaken...${NC}"
aws iam put-user-policy \
    --user-name $IAM_USER_NAME \
    --policy-name "${PROJECT_NAME}-developer-policy" \
    --policy-document file://policies/development-user-policy.json

# Stap 3: Maak Access Keys (optioneel)
echo -e "\n${GREEN}3. Access Keys aanmaken...${NC}"
read -p "Wil je access keys aanmaken voor deze user? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    aws iam create-access-key --user-name $IAM_USER_NAME > access-keys.json
    echo -e "${YELLOW}⚠️  Access keys opgeslagen in access-keys.json - BEWAAR DEZE VEILIG!${NC}"
fi

# Stap 4: Maak Lambda Execution Role
echo -e "\n${GREEN}4. Lambda Execution Role aanmaken...${NC}"
aws iam create-role \
    --role-name $LAMBDA_ROLE_NAME \
    --assume-role-policy-document file://policies/lambda-trust-policy.json \
    2>/dev/null || echo "Role bestaat al"

# Attach basic Lambda execution policy
aws iam attach-role-policy \
    --role-name $LAMBDA_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Attach custom policy voor S3 access
aws iam put-role-policy \
    --role-name $LAMBDA_ROLE_NAME \
    --policy-name "${PROJECT_NAME}-s3-access" \
    --policy-document file://policies/lambda-execution-role-policy.json

# Stap 5: Maak S3 Bucket
echo -e "\n${GREEN}5. S3 Bucket aanmaken...${NC}"
aws s3api create-bucket \
    --bucket $BUCKET_NAME \
    --region $AWS_REGION \
    --create-bucket-configuration LocationConstraint=$AWS_REGION

# Enable versioning (best practice)
aws s3api put-bucket-versioning \
    --bucket $BUCKET_NAME \
    --versioning-configuration Status=Enabled

echo -e "\n${GREEN}✅ Setup voltooid!${NC}"
echo -e "\nGebruik deze waarden in je code:"
echo -e "  S3 Bucket: ${YELLOW}$BUCKET_NAME${NC}"
echo -e "  Lambda Role ARN: ${YELLOW}arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/$LAMBDA_ROLE_NAME${NC}"

# Schrijf config naar bestand voor later gebruik
cat > aws-config.env << EOF
AWS_REGION=$AWS_REGION
S3_BUCKET=$BUCKET_NAME
LAMBDA_ROLE_ARN=arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/$LAMBDA_ROLE_NAME
PROJECT_NAME=$PROJECT_NAME
EOF

echo -e "\nConfig opgeslagen in ${YELLOW}aws-config.env${NC}"