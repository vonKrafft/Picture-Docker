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
import PIL
import re
import shutil
import si_prefix
import sqlite3
import sys
import time
import uuid


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
                `thumbnails` TEXT DEFAULT "[]"
            );
        ''')
        self.conn.commit()

    def select_by_uuid(self, image_uuid: str) -> dict:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images` WHERE `uuid` = :image_uuid LIMIT 1''', { 'image_uuid': str(image_uuid) })
        row = cursor.fetchone()
        return {key: row[key] for key in row.keys()} if row is not None else None

    def select_by_path(self, path_like: str) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''SELECT * FROM `images` WHERE `path` LIKE :path_like ORDER BY `path`''', { 'path_like': str(path_like) + '%' })
        return [{key: row[key] for key in row.keys()} for row in cursor.fetchall()]

    def insert(self, image_uuid: str, filename: str, path: str, thumbnails: list = []) -> None:
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO `images` (`uuid`, `filename`, `path`, `thumbnails`) VALUES (:image_uuid, :filename, :path, :thumbnails)', {
            'image_uuid': str(image_uuid),
            'filename': str(filename),
            'path': str(path),
            'thumbnails': json.dumps(thumbnails)
        })
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] New image {filename} ({image_uuid})")
        self.conn.commit()

    def update(self, image_uuid: str, filename: str, path: str, thumbnails: list = []) -> None:
        cursor = self.conn.cursor()
        cursor.execute('UPDATE `images` SET `filename` = :filename, `path` = :path, `thumbnails` = :thumbnails WHERE `uuid` = :image_uuid', {
            'image_uuid': str(image_uuid),
            'filename': str(filename),
            'path': str(path),
            'thumbnails': json.dumps(thumbnails)
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
    return {}


@routes.get('/image/{image_uuid}')
@aiohttp_jinja2.template('image.jinja2')
async def handle_image(request: 'aiohttp.web.Request') -> dict:
    img = db.select_by_uuid(request.match_info.get('image_uuid', None))

    if img is None or not os.path.isfile(os.path.join(upload_dir, img.get('path'))):
        return aiohttp.web.HTTPNotFound()

    try:
        image = PIL.Image.open(os.path.join(upload_dir, img.get('path')))
    except:
        return aiohttp.web.HTTPInternalServerError()

    img['stat'] = os.stat(os.path.join(upload_dir, img.get('path')))
    if image.format.lower() in ('jpg', 'jpeg'):
        exif = image._getexif() if image._getexif() is not None else dict()
        img = { **{PIL.ExifTags.TAGS.get(tag, tag): value for tag, value in exif.items()}, **img }
        img['Focal'] = int(img.get('FocalLength', (0, 1))[0] / img.get('FocalLength', (0, 1))[1])
        img['Opening'] = round(img.get('FNumber', (0, 1))[0] / img.get('FNumber', (0, 1))[1], 1)
    img['root'], img['extension'] = os.path.splitext(img.get('path'))
    img['thumbnails'] = [{ 'size': thumbnail, 'path': f"{img.get('root')}-{thumbnail}.{img.get('extension').lstrip('.')}" } for thumbnail in json.loads(img['thumbnails'])]
    img['width'], img['height'], img['info'], img['format'] = image.width, image.height, image.info, image.format
    img['resolution'] = round(img.get('width', 0) * img.get('height', 0) / 1000000, 1)
    img['weight'] = si_prefix.si_format(img['stat'].st_size, precision=1)
    try:
        img['localtime'] = time.strptime(img.get('DateTime', ''), '%Y:%m:%d %H:%M:%S')
    except ValueError:
        img['localtime'] = time.localtime(img['stat'].st_ctime)
    img['date'] = time.strftime('%d %B %Y', img['localtime'])
    img['time'] = time.strftime('%a, %H:%M', img['localtime'])

    return {
        'data': img,
    }


@routes.get('/login')
@aiohttp_jinja2.template('login.jinja2')
async def handle_login(request: 'aiohttp.web.Request') -> dict:
    return {
        'token_is_not_set': token is False,
    }


@routes.post('/login')
async def handle_login_form(request: 'aiohttp.web.Request') -> 'aiohttp.web.Response':
    post = await request.post()
    if post.get('token', None) == token:
        session = await aiohttp_session.get_session(request)
        session['token'] = post.get('token')
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Successfully authenticated from {request.remote}")
        return aiohttp.web.HTTPFound('/admin')
    return aiohttp.web.HTTPFound('/login')


@routes.get('/admin')
@aiohttp_jinja2.template('admin.jinja2')
async def handle_admin(request: 'aiohttp.web.Request') -> dict:
    session = await require_authenticated_user(request)
    return {}


@routes.get('/admin/explorer')
@aiohttp_jinja2.template('explorer.jinja2')
async def handle_admin_explorer(request: 'aiohttp.web.Request') -> dict:
    session = await require_authenticated_user(request)

    year = int('0' + re.sub(r'[^0-9]+', '', request.query.get('year', '')))
    month = int('0' + re.sub(r'[^0-9]+', '', request.query.get('month', '')))

    if year > 1970:
        year = f"0000{year}"[-4:]
        if 1 <= month and month <= 12:
            month = f"00{month}"[-2:]
            files = db.select_by_path(os.path.join(year, month))
            for img in files:
                if os.path.isfile(os.path.join(upload_dir, img.get('path'))):
                    img['stat'] = os.stat(os.path.join(upload_dir, img.get('path')))
                    img['weight'] = si_prefix.si_format(img['stat'].st_size, precision=1)
                img['root'], img['extension'] = os.path.splitext(img.get('path'))
                img['thumbnails'] = [{ 'size': thumbnail, 'path': f"{img.get('root')}-{thumbnail}.{img.get('extension').lstrip('.')}" } for thumbnail in json.loads(img['thumbnails'])]
        else:
            files, month = dict(), None
            for img in db.select_by_path(year):
                if re.match(r'^[0-9]{4}/[0-9]{2}/.*$', img.get('path')):
                    m = int(re.sub(r'^[0-9]{4}/([0-9]{2})/.*$', r'\1', img.get('path')))
                    if m not in files:
                        files[m] = { 'name': f"00{m}"[-2:], 'counter': 0, 'st_size': 0, 'hr_size': None}
                    files[m]['counter'] += 1 if os.path.isfile(os.path.join(upload_dir, img.get('path'))) else 0
                    files[m]['st_size'] += os.stat(os.path.join(upload_dir, img.get('path'))).st_size if os.path.isfile(os.path.join(upload_dir, img.get('path'))) else 0
                    files[m]['hr_size'] = si_prefix.si_format(files[m]['st_size'], precision=1)
            files = [files[m] for m in sorted(files)]
    else:
        files, year, month = dict(), None, None
        for img in db.select_by_path(''):
            if re.match(r'^[0-9]{4}/[0-9]{2}/.*$', img.get('path')):
                y = int(re.sub(r'^([0-9]{4})/[0-9]{2}/.*$', r'\1', img.get('path')))
                if y not in files:
                    files[y] = { 'name': f"0000{y}"[-4:], 'counter': 0, 'st_size': 0, 'hr_size': None}
                files[y]['counter'] += 1 if os.path.isfile(os.path.join(upload_dir, img.get('path'))) else 0
                files[y]['st_size'] += os.stat(os.path.join(upload_dir, img.get('path'))).st_size if os.path.isfile(os.path.join(upload_dir, img.get('path'))) else 0
                files[y]['hr_size'] = si_prefix.si_format(files[y]['st_size'], precision=1)
        files = [files[y] for y in sorted(files)]

    return {
        'year': year,
        'month': month,
        'files': files,
    }


@routes.post('/admin/store')
async def handle_admin_store(request: 'aiohttp.web.Request') -> dict:
    session = await require_authenticated_user(request)
    post = await request.post()

    upload = post.get('image')

    if upload.content_type not in ('image/jpeg', 'image/jpg', 'image/png', 'image/gif'):
        return aiohttp.web.HTTPBadRequest()

    if upload.filename.split('.')[-1].lower() not in ('jpeg', 'jpg', 'png', 'gif'):
        return aiohttp.web.HTTPBadRequest()

    image_uuid = uuid.uuid4()
    filename = f"{hashlib.md5(image_uuid.bytes).hexdigest()}.{upload.filename.split('.')[-1].lower()}"
    path = os.path.join(time.strftime('%Y'), time.strftime('%m'))

    os.makedirs(os.path.join(upload_dir, path), exist_ok=True)
    with open(os.path.join(upload_dir, path, filename), 'wb') as file:
        file.write(upload.file.read())

    image = PIL.Image.open(os.path.join(upload_dir, path, filename))
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


def image_resize(image: 'PIL.Image.Image', path: str, root: str, extension: str, new_width: int) -> str:
    new_height = int(new_width * image.height / image.width)
    image = image.resize((new_width, new_height), PIL.Image.ANTIALIAS)
    image.save(os.path.join(path, f"{root}-{new_width}x{new_height}.{extension.lstrip('.')}"), image.format)
    return f"{new_width}x{new_height}"


def image_thumbnail(image: 'PIL.Image.Image', path: str, root: str, extension: str, square: int = 150) -> str:
    width, height = image.size
    if width < height:
        cropped = height - width
        image = image.crop((0, int(math.floor(cropped / 2)), width, int(height - math.ceil(cropped / 2))))
    elif width > height:
        cropped = width - height
        image = image.crop((int(math.floor(cropped / 2)), 0, int(width - math.ceil(cropped / 2)), height))
    image.thumbnail((square, square), PIL.Image.ANTIALIAS)
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
    app.middlewares.append(create_error_middleware({ 400: handle_400, 404: handle_404, 500: handle_500 }))
    return app


if __name__ == '__main__':
    aiohttp.web.run_app(make_app())