#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2019 vonKrafft <contact@vonkrafft.fr>
# 
# This file is part of Picture-Docker
# Source code available on https://github.com/vonKrafft/Picture-Docker
# 
# This file may be used under the terms of the GNU General Public License
# version 3.0 as published by the Free Software Foundation and appearing in
# the file LICENSE included in the packaging of this file. Please review the
# following information to ensure the GNU General Public License version 3.0
# requirements will be met: http://www.gnu.org/copyleft/gpl.html.
# 
# This file is provided AS IS with NO WARRANTY OF ANY KIND, INCLUDING THE
# WARRANTY OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

import aiohttp
import aiohttp_jinja2
import aiohttp_session
import aiohttp_session.cookie_storage
import asyncio
import base64
import cryptography.fernet
import hashlib
import jinja2
import json
import locale
import math
import os
import re
import shutil
import si_prefix
import sqlite3
import sys
import time
import uuid

from PIL import Image
from PIL import ExifTags


# Require Python 3.6+
assert sys.version_info >= (3, 6)


class Database:

    def __init__(self, dbfile: str):
        self.conn = sqlite3.connect(dbfile)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Database initialized ({dbfile})")

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Database closed")

    def create_tables(self) -> None:
        cursor = self.conn.cursor()
        cursor.executescript('''
            CREATE TABLE IF NOT EXISTS `images` (
                `id` INTEGER PRIMARY KEY,
                `uuid` TEXT NOT NULL,
                `filename` TEXT NOT NULL,
                `path` TEXT NOT NULL,
                `caption` TEXT DEFAULT NULL,
                `location` TEXT DEFAULT NULL
            );
        ''')
        self.conn.commit()

    def select(self) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images`''')
        return [{key: row[key] for key in row.keys()} for row in cursor.fetchall()]

    def select_by_uuid(self, image_uuid: str) -> dict:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images` WHERE `uuid` = :image_uuid LIMIT 1''', { 'image_uuid': str(image_uuid) })
        row = cursor.fetchone()
        return {key: row[key] for key in row.keys()} if row is not None else None

    def insert(self, image_uuid: str, filename: str, path: str, captiobn: str = '', location: str = '') -> None:
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO `images` (`uuid`, `filename`, `path`, `caption`, `location`) VALUES (:image_uuid, :filename, :path, :caption, :location)', {
            'image_uuid': str(image_uuid),
            'filename': str(filename),
            'path': str(path),
            'caption': str(caption),
            'location': str(location)
        })
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] New image {filename} ({image_uuid})")
        self.conn.commit()

    def update(self, image_uuid: str, filename: str, path: str, thumbnails: list = []) -> None:
        cursor = self.conn.cursor()
        cursor.execute('UPDATE `images` SET `filename` = :filename, `path` = :path, `caption` = :caption, `location` = :location WHERE `uuid` = :image_uuid', {
            'image_uuid': str(image_uuid),
            'filename': str(filename),
            'path': str(path),
            'caption': str(caption),
            'location': str(location)
        })
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Update image {filename} ({image_uuid})")
        self.conn.commit()

    def delete(self, image_uuid: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM `images` WHERE `uuid` = :image_uuid', {
            'image_uuid': str(image_uuid)
        })
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Delete image {image_uuid}")
        self.conn.commit()


locale.setlocale(locale.LC_ALL, ('fr_FR', 'UTF-8'))
routes = aiohttp.web.RouteTableDef()
db = Database(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'picture.sqlite')))
upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'media')
trash_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'trash')

os.makedirs(upload_dir, exist_ok=True)
os.makedirs(trash_dir, exist_ok=True)

token = os.environ["PICTURE_TOKEN"] if "PICTURE_TOKEN" in os.environ else False

@routes.get('/')
@aiohttp_jinja2.template('index.jinja2')
async def handle_index(request: 'aiohttp.web.Request') -> dict:
    session = await aiohttp_session.get_session(request)

    return {
        'is_authenticated': session.get('token', None) == token,
        'files': db.select(),
    }


@routes.get('/p/{image_uuid}')
@aiohttp_jinja2.template('single.jinja2')
async def handle_page(request: 'aiohttp.web.Request') -> dict:
    session = await aiohttp_session.get_session(request)

    data = db.select_by_uuid(request.match_info.get('image_uuid', None))
    if data is None or not os.path.isfile(os.path.join(upload_dir, data.get('path'))):
        raise aiohttp.web.HTTPNotFound()

    try:
        image = Image.open(os.path.join(upload_dir, data.get('path')))
    except:
        raise aiohttp.web.HTTPInternalServerError()

    data['stat'] = os.stat(os.path.join(upload_dir, data.get('path')))
    if image.format.lower() in ('jpg', 'jpeg'):
        exif = image._getexif() if image._getexif() is not None else dict()
        data = { **{ExifTags.TAGS.get(tag, tag): value for tag, value in exif.items()}, **data }
        data['Focal'] = int(data.get('FocalLength', (0, 1))[0] / data.get('FocalLength', (0, 1))[1])
        data['Opening'] = round(data.get('FNumber', (0, 1))[0] / data.get('FNumber', (0, 1))[1], 1)
    data['root'], data['extension'] = os.path.splitext(data.get('path'))
    data['width'], data['height'], data['info'], data['format'] = image.width, image.height, image.info, image.format
    data['resolution'] = round(data.get('width', 0) * data.get('height', 0) / 1000000, 1)
    data['weight'] = si_prefix.si_format(data['stat'].st_size, precision=1)
    try:
        data['localtime'] = time.strptime(data.get('DateTime', ''), '%Y:%m:%d %H:%M:%S')
    except ValueError:
        data['localtime'] = time.localtime(data['stat'].st_ctime)
    data['date'] = time.strftime('%d %B %Y', data['localtime'])
    data['time'] = time.strftime('%a, %H:%M', data['localtime'])

    return {
        'is_authenticated': session.get('token', None) == token,
        'data': data,
    }


@routes.get('/login')
@aiohttp_jinja2.template('login.jinja2')
async def handle_login(request: 'aiohttp.web.Request') -> dict:
    return {
        'token_is_not_set': token is False,
    }


@routes.post('/login')
async def handle_login(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    post = await request.post()
    if post.get('token', None) == token:
        session = await aiohttp_session.get_session(request)
        session['token'] = post.get('token')
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Successfully authenticated from {request.remote}")
        return aiohttp.web.HTTPFound('/admin')
    return aiohttp.web.HTTPFound('/login')


@routes.get('/upload')
@aiohttp_jinja2.template('upload.jinja2')
async def handle_upload(request: 'aiohttp.web.Request') -> dict:
    session = await aiohttp_session.get_session(request)
    if session.get('token', None) != token:
        raise aiohttp.web.HTTPFound('/login')
    
    return {}


@routes.post('/upload')
async def handle_upload(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    session = await aiohttp_session.get_session(request)
    if session.get('token', None) != token:
        raise aiohttp.web.HTTPFound('/login')

    post = await request.post()
    upload = post.get('image')

    if upload.content_type not in ('image/jpeg', 'image/jpg', 'image/png', 'image/gif'):
        raise aiohttp.web.HTTPBadRequest()

    if upload.filename.split('.')[-1].lower() not in ('jpeg', 'jpg', 'png', 'gif'):
        raise aiohttp.web.HTTPBadRequest()

    image_uuid = uuid.uuid4()
    filename = f"{hashlib.md5(image_uuid.bytes).hexdigest()}.{upload.filename.split('.')[-1].lower()}"
    path = os.path.join(time.strftime('%Y'), time.strftime('%m'))

    os.makedirs(os.path.join(upload_dir, path), exist_ok=True)
    with open(os.path.join(upload_dir, path, filename), 'wb') as file:
        file.write(upload.file.read())

    image = Image.open(os.path.join(upload_dir, path, filename))
    root, extension = os.path.splitext(os.path.basename(image.filename))
    thumbnails = list()
    for width in [1200, 992, 768, 576]:
        if image.width > width:
            thumbnails.append(image_resize(image.copy(), os.path.join(upload_dir, path), root, extension, width))
    if image.width > 150 and image.height > 150:
        thumbnails.append(image_thumbnail(image.copy(), os.path.join(upload_dir, path), root, extension))
    db.insert(image_uuid, upload.filename, os.path.join(path, filename), thumbnails)

    return aiohttp.web.HTTPFound(f'/image/{image_uuid}')


@routes.get('/admin/delete/{image_uuid}')
async def handle_admin_delete(request: 'aiohttp.web.Request') -> dict:
    session = await require_authenticated_user(request)
    img = db.select_by_uuid(request.match_info.get('image_uuid', None))

    if img is None:
        return aiohttp.web.HTTPNotFound()

    img['root'], img['extension'] = os.path.splitext(img.get('path'))
    files = [f"{img.get('root')}-{thumbnail}.{img.get('extension').lstrip('.')}" for thumbnail in json.loads(img['thumbnails'])]
    files.append(img.get('path'))

    for filepath in files:
        if os.path.isfile(os.path.join(upload_dir, filepath)):
            shutil.move(os.path.join(upload_dir, filepath), os.path.join(trash_dir, os.path.basename(filepath)))
    db.delete(request.match_info.get('image_uuid', None))

    return aiohttp.web.HTTPFound(request.headers.get('Referer', '/admin/explorer').replace(f"{request.scheme}://{request.host}", ''))


async def handle_400(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    return aiohttp_jinja2.render_template('errors/400.html', request, {})


async def handle_404(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    return aiohttp_jinja2.render_template('errors/404.html', request, {})


async def handle_500(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    return aiohttp_jinja2.render_template('errors/500.html', request, {})


async def require_authenticated_user(request: 'aiohttp.web.Request') -> 'aiohttp_session.Session':
    session = await aiohttp_session.get_session(request)
    # if session.get('token', None) != token:
    #     raise aiohttp.web.HTTPFound('/login')
    return session


def image_resize(image: 'Image.Image', path: str, root: str, extension: str, new_width: int) -> str:
    new_height = int(new_width * image.height / image.width)
    image = image.resize((new_width, new_height), Image.ANTIALIAS)
    image.save(os.path.join(path, f"{root}-{new_width}x{new_height}.{extension.lstrip('.')}"), image.format)
    return f"{new_width}x{new_height}"


def image_thumbnail(image: 'Image.Image', path: str, root: str, extension: str, square: int = 150) -> str:
    width, height = image.size
    if width < height:
        cropped = height - width
        image = image.crop((0, int(math.floor(cropped / 2)), width, int(height - math.ceil(cropped / 2))))
    elif width > height:
        cropped = width - height
        image = image.crop((int(math.floor(cropped / 2)), 0, int(width - math.ceil(cropped / 2)), height))
    image.thumbnail((square, square), Image.ANTIALIAS)
    image.save(os.path.join(path, f"{root}-{square}x{square}.{extension.lstrip('.')}"), image.format)
    return f"{square}x{square}"


def create_error_middleware(overrides):
    @aiohttp.web.middleware
    async def error_middleware(request, handler):
        try:
            response = await handler(request)
            override = overrides.get(response.status)
            if override:
                return await override(request)
            return response
        except aiohttp.web.HTTPException as ex:
            override = overrides.get(ex.status)
            if override:
                return await override(request)
            raise
    return error_middleware


def make_app() -> aiohttp.web.Application:
    app = aiohttp.web.Application(client_max_size=64 * 1024 ** 2)
    secret_key = base64.urlsafe_b64decode(cryptography.fernet.Fernet.generate_key())
    aiohttp_session.setup(app, aiohttp_session.cookie_storage.EncryptedCookieStorage(secret_key))
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')))
    app.router.add_static('/static', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'))
    app.router.add_static('/media', upload_dir)
    app.router.add_routes(routes)
    #app.middlewares.append(create_error_middleware({ 400: handle_400, 404: handle_404, 500: handle_500 }))
    return app


if __name__ == '__main__':
    aiohttp.web.run_app(make_app())