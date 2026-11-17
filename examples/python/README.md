# Python example

`personal_mail_client.py` is a small `httpx` client for backends (Django,
Flask, FastAPI, scripts and workers).

```python
from personal_mail_client import PersonalMailClient, PersonalMailError

mail = PersonalMailClient("https://your-mail-api.onrender.com", os.environ["MAIL_API_KEY"])

mail.send_email(
    "jane@example.com",
    template="password_reset",
    variables={"name": "Jane", "reset_url": "https://app.example.com/reset?token=..."},
)

mail.notify("business.enquiry", "New enquiry", "Acme Ltd asked for a quote.", Budget="5k")

try:
    mail.send_email("user@example.com", subject="Hi", text="Hello")
except PersonalMailError as exc:
    if exc.retryable:
        ...  # queue for retry
```

Forwarding a portfolio contact form from a Flask or FastAPI backend instead of the browser:

```python
@app.post("/contact")
def contact(form: ContactForm):
    return mail.submit_contact("portfolio", form.name, form.email, form.message)
```
