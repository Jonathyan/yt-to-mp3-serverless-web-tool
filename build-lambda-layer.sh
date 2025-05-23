#!/bin/bash

# Build Lambda Layer voor FFmpeg en yt-dlp
# Dit script bouwt een Lambda Layer met alle dependencies

set -e

echo "🔧 Lambda Layer Builder voor FFmpeg & yt-dlp"
echo "==========================================="

# Variabelen
LAYER_NAME="ffmpeg-ytdlp-layer"
BUILD_DIR="layer-build"
LAYER_DIR="$BUILD_DIR/python"
BIN_DIR="$BUILD_DIR/bin"

# Maak build directories
echo "📁 Build directories aanmaken..."
rm -rf $BUILD_DIR
mkdir -p $LAYER_DIR
mkdir -p $BIN_DIR

# Download FFmpeg static build voor Lambda (Amazon Linux 2)
echo -e "\n📥 FFmpeg downloaden voor Lambda..."
cd $BIN_DIR

# Download pre-built FFmpeg voor Lambda
FFMPEG_URL="https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-linux-64.zip"
curl -L -o ffmpeg.zip $FFMPEG_URL
unzip ffmpeg.zip
rm ffmpeg.zip
chmod +x ffmpeg

# Test FFmpeg
./ffmpeg -version || echo "⚠️  FFmpeg test gefaald - check de binary"

cd ../..

# Installeer Python packages in layer directory
echo -e "\n📦 Python packages installeren..."
pip install --target $LAYER_DIR yt-dlp

# Maak een wrapper script voor FFmpeg pad
echo -e "\n📝 FFmpeg wrapper maken..."
cat > $LAYER_DIR/ffmpeg_location.py << 'EOF'
import os

def get_ffmpeg_path():
    """Get the path to ffmpeg binary in Lambda environment."""
    # In Lambda Layer, binaries zijn in /opt/bin
    lambda_path = '/opt/bin/ffmpeg'
    
    # Voor lokaal testen
    local_path = os.path.join(os.path.dirname(__file__), '..', 'bin', 'ffmpeg')
    
    if os.path.exists(lambda_path):
        return lambda_path
    elif os.path.exists(local_path):
        return os.path.abspath(local_path)
    else:
        # Fallback naar system ffmpeg
        return 'ffmpeg'
EOF

# Zip de layer
echo -e "\n📦 Layer zippen..."
cd $BUILD_DIR
zip -r ../${LAYER_NAME}.zip .
cd ..

# Bereken grootte
LAYER_SIZE=$(du -h ${LAYER_NAME}.zip | cut -f1)
echo -e "\n✅ Layer gebouwd: ${LAYER_NAME}.zip (${LAYER_SIZE})"

# Upload naar AWS
echo -e "\n☁️  Layer uploaden naar AWS..."
read -p "Wil je de layer nu uploaden naar AWS? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    source aws-config.env
    
    LAYER_VERSION=$(aws lambda publish-layer-version \
        --layer-name $LAYER_NAME \
        --description "FFmpeg and yt-dlp for video processing" \
        --zip-file fileb://${LAYER_NAME}.zip \
        --compatible-runtimes python3.12 \
        --compatible-architectures arm64 x86_64 \
        --query 'LayerVersionArn' \
        --output text)
    
    echo -e "\n✅ Layer gepubliceerd!"
    echo -e "Layer ARN: $LAYER_VERSION"
    
    # Voeg toe aan config
    echo "LAMBDA_LAYER_ARN=$LAYER_VERSION" >> aws-config.env
fi

echo -e "\n🎉 Klaar!"