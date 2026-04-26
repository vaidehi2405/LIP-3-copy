import requests

url = "https://saksham-mcp-server-a7gq.onrender.com/create_email_draft"
payload = {
    "to": "saurabhdeosarkar101@gmail.com",
    "subject": "Format Testing — Please Check",
    "body": "This is raw. <b>This is bold.</b>",
    "html": "<html><body>This is html body. <b>Is it bold?</b></body></html>",
    "isHtml": True,
    "is_html": True
}
requests.post(url, json=payload)
print("done")
