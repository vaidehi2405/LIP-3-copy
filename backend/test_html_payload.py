import requests
import json

url = "https://saksham-mcp-server-a7gq.onrender.com/create_email_draft"

# Test 1: Sending HTML inside 'body'
payload1 = {
    "to": "saurabhdeosarkar101@gmail.com",
    "subject": "Test HTML via body",
    "body": "<h1>Is this big?</h1><p><b>Bold?</b></p>"
}

# Test 2: Sending HTML via 'html_body'
payload2 = {
    "to": "saurabhdeosarkar101@gmail.com",
    "subject": "Test HTML via html_body",
    "body": "Fallback plain text.",
    "html_body": "<h1>Is this big?</h1><p><b>Bold?</b></p>"
}

print("Executing test 1")
requests.post(url, json=payload1)

print("Executing test 2")
requests.post(url, json=payload2)

print("Tests submitted to MCP.")
