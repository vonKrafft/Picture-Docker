# Picture-Docker

**Picture** is a minimalist web application for sharing photos and managing them like a portfolio.

The web interface offers two pages: a home page to view the list of photos, and a page to view the actual photo with its metadata (location, description, date, capture device, settings, etc.).

Once authenticated with the token defined in `docker-compose.yml`, you are allowed to upload, modify or delete a photo.

> **Note:** This project is initially for personal use, the WebUI is in French.

![Web interface of Picture](https://raw.githubusercontent.com/vonKrafft/Picture-Docker/master/preview.png)

_I know, the design is strongly inspired by instagram. Blame me but I find it simple and effective :)_

## Installation

You have to install `docker` and `docker-compose` (https://docs.docker.com/compose/install/). Remember to set your own token as an environment variable **PICTURE_TOKEN** in `docker-compose.yml`!

```
$ git clone https://github.com/vonKrafft/Picture-Docker
$ cd Picture-Docker
$ docker-compose up -d
```

The user within the Docker container has the UID and the GID 1000. Make sure the directories `data`, `media` and `trash` have the correct permissions and the right owner.

```
$ cd Picture-Docker
$ chown -R 1000:1000 web-picture/{data,media,trash}
$ chmod 775 web-picture/{data,media,trash}
```

## Dependencies

**Docker**

- Python:3-alpine - Docker Official Images (https://hub.docker.com/_/python)

**Web interface**

- Bootstrap v4.3.1 (https://getbootstrap.com/)
- jQuery v3.4.1 (https://jquery.com/)
- PopperJS v1.14.7 (https://popper.js.org/)

## License

This source code may be used under the terms of the GNU General Public License version 3.0 as published by the Free Software Foundation and appearing in the file LICENSE included in the packaging of this file. Please review the following information to ensure the GNU General Public License version 3.0 requirements will be met: http://www.gnu.org/copyleft/gpl.html.