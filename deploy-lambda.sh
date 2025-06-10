#!/bin/bash

# Deploy Lambda Function Script
# Voor Sprint 0 - handmatige deployment met cookies support

set -e

echo "🚀 Lambda Function Deployment with Cookies Support"
echo "=================================================="

# Load config
if [ ! -f "aws-config.env" ]; then
    echo "❌ aws-config.env not found!"
    echo "Run aws-setup.sh first to create configuration"
    exit 1
fi

source aws-config.env

FUNCTION_NAME="${PROJECT_NAME}-video-processor"
HANDLER="lambda_function.lambda_handler"
RUNTIME="python3.12"
TIMEOUT=300  # 5 minuten voor video processing
MEMORY_SIZE=1024  # 1GB RAM
COOKIES_SECRET_NAME="mp3maker/youtube-cookies"

echo "📋 Configuration:"
echo "  Function Name: $FUNCTION_NAME"
echo "  S3 Bucket: $S3_BUCKET"
echo "  Cookies Secret: $COOKIES_SECRET_NAME"
echo "  Lambda Layer: $LAMBDA_LAYER_ARN"

# Check if secrets manager secret exists
echo -e "\n🔍 Checking if cookies secret exists..."
if aws secretsmanager describe-secret --secret-id "$COOKIES_SECRET_NAME" >/dev/null 2>&1; then
    echo "✅ Cookies secret found: $COOKIES_SECRET_NAME"
else
    echo "⚠️  Cookies secret not found: $COOKIES_SECRET_NAME"
    echo "💡 You can create it later with:"
    echo "   aws secretsmanager create-secret --name $COOKIES_SECRET_NAME --secret-string file://cookies.json"
fi

# Package de Lambda functie
echo -e "\n📦 Lambda functie packagen..."
rm -rf lambda-package
mkdir lambda-package

# Check welke Lambda code we hebben
if [ -f "./lambda/lambda_function.py" ]; then
    echo "📁 Using lambda/lambda_function.py"
    cp ./lambda/lambda_function.py lambda-package/
elif [ -f "lambda_function.py" ]; then
    echo "📁 Using lambda_function.py from root"
    cp lambda_function.py lambda-package/
else
    echo "❌ Lambda function code not found!"
    echo "Expected: ./lambda/lambda_function.py or ./lambda_function.py"
    exit 1
fi

cd lambda-package
zip -r ../lambda-deployment.zip .
cd ..

echo "✅ Lambda package created: lambda-deployment.zip"

# Deploy of update Lambda
echo -e "\n☁️  Lambda functie deployen..."

# Check of functie bestaat
if aws lambda get-function --function-name $FUNCTION_NAME >/dev/null 2>&1; then
    echo "📝 Functie bestaat al, updating..."
    
    # Update function code
    echo "🔄 Updating function code..."
    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://lambda-deployment.zip
    
    # Update configuration
    echo "🔧 Updating function configuration..."
    aws lambda update-function-configuration \
        --function-name $FUNCTION_NAME \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --environment Variables="{
            S3_BUCKET=\"$S3_BUCKET\",
            COOKIES_SECRET_NAME=\"$COOKIES_SECRET_NAME\"
        }" \
        --layers $LAMBDA_LAYER_ARN
        
    echo "✅ Lambda function updated successfully!"
    
else
    echo "✨ Nieuwe functie aanmaken..."
    
    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role $LAMBDA_ROLE_ARN \
        --handler $HANDLER \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --environment Variables="{
            S3_BUCKET=\"$S3_BUCKET\",
            COOKIES_SECRET_NAME=\"$COOKIES_SECRET_NAME\"
        }" \
        --layers $LAMBDA_LAYER_ARN \
        --zip-file fileb://lambda-deployment.zip \
        --architectures arm64
        
    echo "✅ Lambda function created successfully!"
fi

# Verify environment variables
echo -e "\n📋 Current environment variables:"
aws lambda get-function-configuration \
    --function-name $FUNCTION_NAME \
    --query 'Environment.Variables' \
    --output table

# Test de functie
echo -e "\n🧪 Lambda functie testen..."
read -p "Wil je de functie testen met een test event? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Maak test event als het niet bestaat
    if [ ! -f "test-event.json" ]; then
        echo "📝 Creating test event..."
        cat > test-event.json << EOF
{
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "start_time": "0:10",
    "end_time": "0:30",
    "bitrate": "96k"
}
EOF
    fi
    
    echo "🔄 Test uitvoeren (dit kan even duren)..."
    echo "⏱️  Testing with YouTube URL: $(cat test-event.json | grep youtube_url | cut -d'"' -f4)"
    
    aws lambda invoke \
        --function-name $FUNCTION_NAME \
        --payload file://test-event.json \
        --cli-binary-format raw-in-base64-out \
        response.json
    
    echo -e "\n📋 Response:"
    if command -v jq &> /dev/null; then
        cat response.json | jq .
    else
        cat response.json
        echo  # Add newline
    fi
    
    # Check if test was successful
    if grep -q '"statusCode": 200' response.json; then
        echo -e "\n✅ Test successful! Lambda function is working."
    else
        echo -e "\n⚠️  Test completed with errors. Check the response above."
        echo "💡 Common issues:"
        echo "   - YouTube video might be restricted"
        echo "   - Cookies might be needed (upload to Secrets Manager)"
        echo "   - FFmpeg layer might not be working"
    fi
fi

# Opruimen
echo -e "\n🧹 Cleaning up temporary files..."
rm -f lambda-deployment.zip
rm -rf lambda-package

# Show final information
echo -e "\n✅ Deployment voltooid!"
echo "📊 Function Details:"
echo "  Function Name: $FUNCTION_NAME"
echo "  Function ARN: $(aws lambda get-function --function-name $FUNCTION_NAME --query 'Configuration.FunctionArn' --output text)"
echo "  Runtime: $RUNTIME"
echo "  Memory: ${MEMORY_SIZE}MB"
echo "  Timeout: ${TIMEOUT}s"

echo -e "\n💡 Next Steps:"
echo "1. Upload cookies to Secrets Manager if you haven't already:"
echo "   aws secretsmanager put-secret-value --secret-id $COOKIES_SECRET_NAME --secret-string file://cookies.json"
echo "2. Test with a real church service YouTube URL"
echo "3. Continue with Sprint 1 (Web Interface)"

echo -e "\n🔗 Useful Commands:"
echo "  View logs: sam logs -n $FUNCTION_NAME --tail"
echo "  Test again: aws lambda invoke --function-name $FUNCTION_NAME --payload file://test-event.json response.json"