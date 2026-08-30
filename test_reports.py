import requests

session = requests.Session()
response = session.post('http://127.0.0.1:5000/login', data={'username': 'subratakumar.pradhan', 'password': 'admin123'})
if response.status_code == 200:
    res = session.get('http://127.0.0.1:5000/admin/reports')
    if res.status_code == 200:
        print("Success! 200 OK")
    else:
        print(f"Failed! {res.status_code} {res.text[:200]}")
else:
    print(f"Login failed: {response.status_code}")
