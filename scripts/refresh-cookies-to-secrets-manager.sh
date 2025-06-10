#!/bin/bash

# 1. Installeer dependencies
# pip install cryptography

# 2. Sluit Brave browser VOLLEDIG
# 3. Run het script
# python3 brave_cookie_extractor.py

# 4. Upload naar AWS
aws secretsmanager put-secret-value \
    --secret-id mp3maker/youtube-cookies \
    --secret-string file://cookies/brave-youtube-cookies-default.json