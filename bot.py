import os
import requests

API_KEY = os.environ["AMADEUS_API_KEY"]
API_SECRET = os.environ["AMADEUS_API_SECRET"]

# 1. Access token ophalen
auth_url = "https://test.api.amadeus.com/v1/security/oauth2/token"
auth_data = {
    "grant_type": "client_credentials",
    "client_id": API_KEY,
    "client_secret": API_SECRET,
}
auth_response = requests.post(auth_url, data=auth_data)
auth_response.raise_for_status()
token = auth_response.json()["access_token"]

print("✅ Access token opgehaald:", token[:20], "...")
