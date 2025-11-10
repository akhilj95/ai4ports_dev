# Backend

run using 
python manage.py runserver

You can view the schema using url .../schema-viewer/

There is a postgres dumpfile in data/ if you want to load it
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'mydb', 
        'USER': 'myuser',
        'PASSWORD': 'mypassword',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}


### 1. Create YOUR Admin User

Use this method to create your superuser to access the admin panel.

1.  Run the `createsuperuser` command:
    ```bash
    python manage.py createsuperuser
    ```
2.  Follow the prompts to set a username, email, and a secure password.