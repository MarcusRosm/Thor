#!/usr/bin/env bash
# Authenticate against the Thor app's /login endpoint

BASE_URL="${1:-http://127.0.0.1:8000}"

# Step 1: Login and extract the token
TOKEN=$(curl -s -X POST "${BASE_URL}/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password"}' | jq -r '.token'
)
echo "Token: ${TOKEN}"

# Step 2: Access the protected endpoint with the token
curl -s "${BASE_URL}/protected" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.'