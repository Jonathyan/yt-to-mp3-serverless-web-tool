#!/bin/bash

# Maak een secret aan voor YouTube cookies
aws secretsmanager create-secret \
    --name "mp3maker/youtube-cookies" \
    --description "YouTube cookies voor video downloads" \
    --secret-string file://cookies/brave-youtube-cookies.json

# Of als je de cookies als string hebt:
# aws secretsmanager create-secret \
#     --name "mp3maker/youtube-cookies" \
#     --description "YouTube cookies voor video downloads" \
#     --secret-string '{
#         "cookies": "your_cookie_string_here",
#         "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
#     }'