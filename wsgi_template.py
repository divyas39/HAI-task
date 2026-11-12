"""Template for the PythonAnywhere WSGI file. NOT used when running locally.

Copy this into the WSGI editor on the Web tab (the file at
/var/www/<username>_pythonanywhere_com_wsgi.py), replace every <placeholder>, and Reload.

That file lives outside this repo, which is the point: the secrets below never get committed.
Replace its entire contents -- PythonAnywhere pre-fills it with a Django example.
"""
import os
import sys

# 1. put the checkout on the import path
path = "/home/<username>/HAI-task"
if path not in sys.path:
    sys.path.insert(0, path)

# 2. the secrets. Generate real values with:
#    python -c "import secrets; print(secrets.token_urlsafe(32))"
os.environ["SECRET_KEY"] = "<paste a random 32-byte value>"
os.environ["EXPORT_TOKEN"] = "<paste a different random value>"
# live AI hints; without it the app serves the stored A2 detector outputs instead
os.environ["GEMINI_API_KEY"] = "<your Gemini API key>"

# 3. the database lives OUTSIDE the checkout, so git pull / git clean can never touch
#    collected data, and a redeploy leaves it untouched.
os.environ["DB_PATH"] = "/home/<username>/study.db"

# 4. the site is served over HTTPS, so mark the session cookie secure
os.environ["HTTPS_ONLY"] = "1"

from app import app as application  # noqa: E402
