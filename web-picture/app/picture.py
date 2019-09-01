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
                `uuid` TEXT NOT NULL DEFAULT "",
                `filename` TEXT NOT NULL DEFAULT "",
                `path` TEXT NOT NULL DEFAULT "",
                `thumbnail` TEXT NOT NULL DEFAULT "",
                `caption` TEXT DEFAULT NULL,
                `location` TEXT DEFAULT NULL
            );
        ''')
        self.conn.commit()

    def select(self) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images` ORDER BY `id` DESC''')
        return [{key: row[key] for key in row.keys()} for row in cursor.fetchall()]

    def select_by_uuid(self, image_uuid: str) -> dict:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images` WHERE `uuid` = :image_uuid LIMIT 1''', { 'image_uuid': str(image_uuid) })
        row = cursor.fetchone()
        return {key: row[key] for key in row.keys()} if row is not None else None

    def select_hashtag(self, hashtag: str) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images` WHERE `caption` LIKE :hashtag ORDER BY `id` DESC''', {
            'hashtag': f"%#{hashtag}%"
        })
        return [{key: row[key] for key in row.keys()} for row in cursor.fetchall()]

    def insert(self, image_uuid: str, filename: str, path: str, thumbnail: str, caption: str = '', location: str = '') -> None:
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO `images` (`uuid`, `filename`, `path`, `thumbnail`, `caption`, `location`) VALUES (:image_uuid, :filename, :path, :thumbnail, :caption, :location)', {
            'image_uuid': str(image_uuid),
            'filename': str(filename),
            'path': str(path),
            'thumbnail': str(thumbnail),
            'caption': str(caption),
            'location': str(location)
        })
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] New image {filename} ({image_uuid})")
        self.conn.commit()

    def update(self, image_uuid: str, caption: str = '', location: str = '') -> None:
        cursor = self.conn.cursor()
        cursor.execute('UPDATE `images` SET `caption` = :caption, `location` = :location WHERE `uuid` = :image_uuid', {
            'image_uuid': str(image_uuid),
            'caption': str(caption),
            'location': str(location)
        })
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Update image {image_uuid}")
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

    pictures = db.select() if request.query.get('hashtag', None) is None else db.select_hashtag(request.query.get('hashtag'))
    hashtags = [m.group(1) for data in db.select() for m in re.finditer(r'#(\w+)', data.get('caption'))]

    return {
        'is_authenticated': session.get('token', None) == token,
        'token_is_not_set': token is False,
        'pictures': pictures,
        'hashtags': sorted(hashtags),
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
        'token_is_not_set': token is False,
        'data': data,
    }


@routes.post('/p/{image_uuid}')
async def handle_edition(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    session = await aiohttp_session.get_session(request)
    if session.get('token', None) != token:
        raise aiohttp.web.HTTPUnauthorized()

    data = db.select_by_uuid(request.match_info.get('image_uuid', None))
    if data is None:
        raise aiohttp.web.HTTPNotFound()

    post = await request.post()
    db.update(data.get('uuid'), post.get('caption', ''), post.get('location', ''))

    return aiohttp.web.HTTPFound(f"/p/{data.get('uuid')}")


@routes.delete('/p/{image_uuid}')
async def handle_deletion(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    session = await aiohttp_session.get_session(request)
    if session.get('token', None) != token:
        raise aiohttp.web.HTTPUnauthorized()

    data = db.select_by_uuid(request.match_info.get('image_uuid', None))
    if data is None:
        raise aiohttp.web.HTTPNotFound()

    if os.path.isfile(os.path.join(upload_dir, data.get('path'))):
        shutil.move(os.path.join(upload_dir, data.get('path')), os.path.join(trash_dir, os.path.basename(data.get('path'))))
    db.delete(request.match_info.get('image_uuid', None))

    return aiohttp.web.HTTPAccepted()


@routes.post('/sign-in')
async def handle_signin(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    post = await request.post()
    if post.get('token', None) == token:
        session = await aiohttp_session.new_session(request)
        session['token'] = post.get('token')
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Successfully authenticated from {request.remote}")
    return aiohttp.web.HTTPFound(f"/p/{post.get('uuid')}" if post.get('uuid', False) else '/')


@routes.get('/sign-out')
@aiohttp_jinja2.template('login.jinja2')
async def handle_signout(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    session = await aiohttp_session.new_session(request)
    session['token'] = None
    return aiohttp.web.HTTPFound('/')


@routes.post('/store')
async def handle_store(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
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

    thumbnail = image_thumbnail(path, filename, 384)

    db.insert(image_uuid, upload.filename, os.path.join(path, filename), thumbnail, post.get('caption', ''), post.get('location', ''))

    return aiohttp.web.HTTPFound(f'/p/{image_uuid}')


async def handle_400(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    return aiohttp_jinja2.render_template('errors/400.html', request, {})


async def handle_404(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    return aiohttp_jinja2.render_template('errors/404.html', request, {})


async def handle_500(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    return aiohttp_jinja2.render_template('errors/500.html', request, {})


def image_thumbnail(path: str, filename: str, square: int = 150) -> str:
    image = Image.open(os.path.join(upload_dir, path, filename))
    root, extension = os.path.splitext(os.path.basename(image.filename))
    width, height = image.size
    if image.width > square and image.height > square:
        if width < height:
            image = image.crop((0, int(math.floor((height - width) / 2)), width, int(height - math.ceil((height - width) / 2))))
        elif width > height:
            image = image.crop((int(math.floor((width - height) / 2)), 0, int(width - math.ceil((width - height) / 2)), height))
        image.thumbnail((square, square), Image.ANTIALIAS)
        image.save(os.path.join(upload_dir, path, f"{root}-{square}x{square}.{extension.lstrip('.')}"), image.format)
        return os.path.join(path, f"{root}-{square}x{square}.{extension.lstrip('.')}")
    return os.path.join(path, filename)


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