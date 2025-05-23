#!/bin/bash

# Deploy Lambda Function Script
# Voor Sprint 0 - handmatige deployment

set -e

echo "🚀 Lambda Function Deployment"
echo "============================"

# Load config
source aws-config.env

FUNCTION_NAME="${PROJECT_NAME}-video-processor"
HANDLER="lambda_function.lambda_handler"
RUNTIME="python3.12"
TIMEOUT=300  # 5 minuten voor video processing
MEMORY_SIZE=1024  # 1GB RAM

# Package de Lambda functie
echo "📦 Lambda functie packagen..."
rm -rf lambda-package
mkdir lambda-package
cp lambda_function.py lambda-package/
cd lambda-package
zip -r ../lambda-deployment.zip .
cd ..

# Deploy of update Lambda
echo -e "\n☁️  Lambda functie deployen..."

# Check of functie bestaat
if aws lambda get-function --function-name $FUNCTION_NAME 2>/dev/null; then
    echo "📝 Functie bestaat al, updating..."
    
    # Update function code
    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://lambda-deployment.zip
    
    # Update configuration
    aws lambda update-function-configuration \
        --function-name $FUNCTION_NAME \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --environment Variables="{S3_BUCKET=$S3_BUCKET}" \
        --layers $LAMBDA_LAYER_ARN
else
    echo "✨ Nieuwe functie aanmaken..."
    
    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role $LAMBDA_ROLE_ARN \
        --handler $HANDLER \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --environment Variables="{S3_BUCKET=$S3_BUCKET}" \
        --layers $LAMBDA_LAYER_ARN \
        --zip-file fileb://lambda-deployment.zip \
        --architectures arm64
fi

# Test de functie
echo -e "\n🧪 Lambda functie testen..."
read -p "Wil je de functie testen met een test event? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Maak test event
    cat > test-event.json << EOF
{
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "start_time": "0:10",
    "end_time": "0:30",
    "bitrate": "96k"
}
EOF
    
    echo "🔄 Test uitvoeren (dit kan even duren)..."
    aws lambda invoke \
        --function-name $FUNCTION_NAME \
        --payload file://test-event.json \
        --cli-binary-format raw-in-base64-out \
        response.json
    
    echo -e "\n📋 Response:"
    cat response.json | jq .
fi

# Opruimen
rm -f lambda-deployment.zip
rm -rf lambda-package

echo -e "\n✅ Deployment voltooid!"
echo -e "Function ARN: $(aws lambda get-function --function-name $FUNCTION_NAME --query 'Configuration.FunctionArn' --output text)"