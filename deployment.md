# Deployment

There are a number of tools and libraries included in this repository. One is a web server `wm-diffing-server`, which can be deployed to a remote machine to be used in conjuction with the other Web Monitoring projects.


## Set up your machine (first time only)

### Set up Python environment

First, SSH into your server, update the package manager, and install `nginx`, `git`, `build-essential`, and `libxml2-dev`. On Debian or Ubuntu Linux, you should run:

```sh
$ sudo apt-get update
$ sudo apt-get install git nginx build-essential libxml2-dev
```

Next, install [`conda`](https://conda.io/), which we’ll use to manage Python versions and environments. You can install either [*Anaconda*](https://www.continuum.io/downloads) (the full-featured version with extra packages and tools) or [*Miniconda*](https://conda.io/miniconda.html) (the minimal, light-weight version). Minconda is recommended to keep the server as simple as possible.

```sh
# Find the URL of the installer you want to use.
# For Anaconda, see: https://www.continuum.io/downloads for download URLs
# For Miniconda, see: https://conda.io/miniconda.html for download URLs
$ curl <conda_url> > conda_installer.sh
# e.g: curl https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh > conda_installer.sh
```

Then run the installer. (These parameters get us a system-wide install so the web server can use it.)

```sh
$ sudo bash conda_installer.sh -b -p /opt/conda
```

Finally, ensure that you can access conda by creating a new conda group and adding yourself to it.

```sh
# Create a group for conda and add yourself to it
$ sudo groupadd conda
$ sudo usermod -a -G conda <your_username>

# Ensure users in that group have access to conda
$ sudo chgrp -R conda /opt/conda
$ sudo chmod 770 -R /opt/conda
```


### Install the application

Next, we need to actually install `web-monitoring-processing` in the `/var/www/web-monitoring-processing` directory:

```sh
$ cd /var/www

# Make the directory first to ensure it does not get installed for the root user
$ sudo mkdir web-monitoring-processing
$ sudo chown <your_user> web-monitoring-processing

# Clone the git repo for the project
$ git clone https://github.com/edgi-govdata-archiving/web-monitoring-processing.git
```

Run the actual installer:

```sh
$ cd web-monitoring-processing

# Create a new conda environment.
$ conda create -n web-monitoring-processing
$ conda activate web-monitoring-processing

# Install packages
$ while read requirement; do conda install --yes $requirement; done < requirements.txt
$ python setup.py install
```

Now, test that your installation actually works by running the diffing server on port 8000:

```sh
$ conda activate web-monitoring-processing
$ wm-diffing-server --port 8000
```

Open a web browser and try browsing to: `http://[IP address for your server]:8000/html_text_diff`

You should get a 500 error because you didn't provide the right arguments :P

Press `ctrl+c` to stop the server.


### Set up Supervisor

Next, we’ll set up Supervisor, a tool that will automatically start several copies of the diffing server and restart them if they crash. First, install it and get it running:

```sh
$ sudo apt-get install supervisor
$ sudo service supervisor start
```

After that, create a configuration file for our server:

```sh
$ sudo vim /etc/supervisor/conf.d/wm-diffing-server.conf
```

The content of this file should look like:

```ini
; We run four server instances; one per processor core.
; If you're looking to minimize cpu load, run fewer processes.
; BTW, Tornado processes are single threaded.
; To take advantage of multiple cores, you'll need multiple processes.

[program:wm-diffing-server-8000]
command=/opt/conda/envs/web-monitoring-processing/bin/wm-diffing-server --port 8000
stderr_logfile = /var/log/supervisor/tornado-stderr.log
stdout_logfile = /var/log/supervisor/tornado-stdout.log
environment=PAGE_FREEZER_API_KEY=<page_freezer_key>
stopasgroup=true

[program:wm-diffing-server-8001]
command=/opt/conda/envs/web-monitoring-processing/bin/wm-diffing-server --port 8001
stderr_logfile = /var/log/supervisor/tornado-stderr.log
stdout_logfile = /var/log/supervisor/tornado-stdout.log
environment=PAGE_FREEZER_API_KEY=<page_freezer_key>
stopasgroup=true

[program:wm-diffing-server-8002]
command=/opt/conda/envs/web-monitoring-processing/bin/wm-diffing-server --port 8002
stderr_logfile = /var/log/supervisor/tornado-stderr.log
stdout_logfile = /var/log/supervisor/tornado-stdout.log
environment=PAGE_FREEZER_API_KEY=<page_freezer_key>
stopasgroup=true

[program:wm-diffing-server-8003]
command=/opt/conda/envs/web-monitoring-processing/bin/wm-diffing-server --port 8003
stderr_logfile = /var/log/supervisor/tornado-stderr.log
stdout_logfile = /var/log/supervisor/tornado-stdout.log
environment=PAGE_FREEZER_API_KEY=<page_freezer_key>
stopasgroup=true
```

You can add or remove as many copies of the program as you like, but note that each should be on a separate port. Also make sure fill in `<page_freeer_key>` with your key. You can also leave this line out entirely if you choose not to use PageFreezer diffs.

Then, reload Supervisor’s configuration:

```sh
$ sudo supervisorctl reread
$ sudo supervisorctl update
```

You can check that your servers are now running with:

```sh
$ sudo supervisorctl status
> wm-diffing-server-8000           RUNNING   pid 29929, uptime 0:33:05
> wm-diffing-server-8001           RUNNING   pid 29930, uptime 0:33:05
> wm-diffing-server-8002           RUNNING   pid 29931, uptime 0:33:05
> wm-diffing-server-8003           RUNNING   pid 29932, uptime 0:33:05
```

Try pointing your web browser to the server again without manually running the server this time.


### Use Nginx to route HTTP connections to the diffing server instances

Finally, we’ll use Nginx to proxy HTTP connections through to the diffing servers. This way, Nginx can act as a load balancer across the four services. It can also handle things like SSL, static file serving and the like if we add them in the future.

Create a new web site configuration:

```sh
$ sudo vim /etc/nginx/sites-available/web-monitoring-processing
```

The content of this file should look like:

```nginx
upstream differs {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    server 127.0.0.1:8003;
}

server {
    listen 80;

    # Allow file uploads
    client_max_body_size 50M;

    # ...other standard URLs here, like robots.txt or static files; not necessary now...

    # Send all paths to the diffing server
    location / {
        proxy_pass_header Server;
        proxy_set_header Host $http_host;
        proxy_redirect off;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Scheme $scheme;
        proxy_pass http://differs;
    }
}
```

Then disable the existing default site and enable the one you just created.

```sh
$ sudo rm /etc/nginx/sites-enabled/default
$ sudo ln -s /etc/nginx/sites-available/web-monitoring-processing /etc/nginx/sites-enabled/web-monitoring-processing
$ sudo systemctl restart nginx
```

This time, you should be able to browse directly to your server’s IP without using a special port and get the same response as before:

`http://[IP address for your server]/html_text_diff`

Now you’ve got a working deployment!


## Deploy new releases

When new versions of `web-monitoring-processing` are ready to deploy, use `git` to checkout the correct code, install it, and restart your servers:

```sh
$ cd /var/www/web-monitoring-processing
$ git pull
$ conda activate web-monitoring-processing
$ python setup.py install
$ sudo supervisorctl restart wm-diffing-server-8000
$ sudo supervisorctl restart wm-diffing-server-8001
$ sudo supervisorctl restart wm-diffing-server-8002
$ sudo supervisorctl restart wm-diffing-server-8003
```
