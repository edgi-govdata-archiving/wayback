In order to run the module of get_article_text
# Step 1 - Docker Setup
The directory has file - `Dockerfile`. 

Docker is an open-source project that automates the deployment of applications inside software containers. 

Before building and running Docker, one needs to setup Docker.

Follow the detailed documentation - https://docs.docker.com/engine/installation/#platform-support-matrix

# Step 2 - Docker Run

Once Docker is setup, start the docker service.
`sudo service docker start`
+ If the docker service isn't started, execution of any docker command returns - 
```
docker: Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?.
```

In order to run a Docker container, we need an image.
1. Build the docker image

In order to build the docker image, run the `Docker build` command in the directory where `Dockerfile` file exists. Otherwise, if you do it in wrong directory, it returns an error (`File not found`).

`docker build -t yay .`

Pay due attention to '.' (period) - Otherwise it returns `illegal attribute error`.

2. Run the docker container

Once the docker image is built, spin the docker container.

`docker run -t yay`

# Step 2 - HTTP Request
then POST localhost:8000 with 
{
    "rawHtml": "someRawHtml"
}

and you'll get
{
    "articleText": "hopefully just the text of the article and not the text of the menus and junk",
    "rawHtml": "what you imput"
}
