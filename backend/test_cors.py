"""Quick test to verify CORS configuration"""
import requests

# Test OPTIONS request (preflight)
print("Testing OPTIONS (preflight) request...")
response = requests.options(
    "http://127.0.0.1:8000/api/auth/login",
    headers={
        "Origin": "http://localhost:5174",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type,Authorization"
    }
)
print(f"Status: {response.status_code}")
print(f"Headers:")
for key, value in response.headers.items():
    if "Access-Control" in key:
        print(f"  {key}: {value}")

if response.status_code == 200 and "Access-Control-Allow-Origin" in response.headers:
    print("\n✅ CORS is working!")
else:
    print("\n❌ CORS is NOT working properly")
    print(f"   Status: {response.status_code}")
    print(f"   Allow-Origin header: {response.headers.get('Access-Control-Allow-Origin', 'MISSING')}")

