import re
import time
import json
import logging
import hashlib
import base64
import asyncio

from aiohttp import web

import markdown2
from coroweb import get, post
from models import User, Comment, Blog, next_id
from apis import APIError, APIValueError, APIResourceNotFoundError, APIPermissionError, Page
from config import configs


logging.basicConfig(level=logging.INFO)


COOKIE_NAME = "awesession"
_COOKIE_KEY = configs.session.secret
_RE_EMAIL = re.compile(
    r"^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$"
)
_RE_SHA1 = re.compile(
    r"^[0-9a-f]{40}$"
)


def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()


def get_page_index(s):
    p = 1
    try:
        p = int(s)
    except ValueError:
        pass
    if p < 1:
        p = 1
    return p


def text2html(text):
    ls = map(
        lambda s: "<p>{}</p>".format(
            s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ),
        filter(lambda s: s.strip() != "", text.split("\n"))
    )
    return "".join(ls)


def user2cookie(user, max_age):
    expires = str(int(time.time() + max_age))
    s = "%s-%s-%s-%s" % (user.id, user.passwd, expires, _COOKIE_KEY)
    return "{}-{}-{}".format(
        user.id, expires, hashlib.sha1(s.encode("utf-8")).hexdigest()
    )


async def cookie2user(cookie_str):
    if not cookie_str:
        return None
    try:
        tmp = cookie_str.split("-")
        if len(tmp) != 3:
            return None
        id, expires, sha1 = tmp
        if int(expires) < time.time():
            return None
        user = await User.find(id)
        if user is None:
            return None
        s = "{}-{}-{}-{}".format(id, user.passwd, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode("utf-8")).hexdigest():
            logging.info("invalid sha1")
            return None
        user.passwd = "******"
        return user
    except Exception as e:
        logging.exception(e)
        return None


@get('/')
async def index(*, page="1"):
    p_index = get_page_index(page)
    cnt = await Blog.findNumber("count(id)")
    p = Page(cnt, p_index)
    if cnt == 0:
        blogs = []
    else:
        blogs = await Blog.findAll(orderBy="created_at desc", limit=(p.offset, p.limit))
    return {
        "__template__": "blogs.html",
        "page": p,
        "blogs": blogs
    }


@get("/register")
def register():
    return {
        "__template__": "register.html"
    }


@get("/signin")
def signin():
    return {
        "__template__": "signin.html"
    }


@get("/signout")
def signout(request):
    referer = request.headers.get("Referer")
    ret = web.HTTPFound(referer or "/")
    ret.set_cookie(
        COOKIE_NAME,
        "-deleted-",
        max_age=0,
        httponly=True
    )
    logging.info("user signed out.")
    return ret


@post("/api/authenticate")
async def authenticate(*, email, passwd):
    if not email:
        raise APIValueError("email", "Invalid email.")
    if not passwd:
        raise APIValueError("passwd", "Invalid password.")

    users = await User.findAll("email=?", [email])
    if len(users) == 0:
        raise APIValueError("email", "Email not exist.")

    user = users[0]
    sha1 = hashlib.sha1()
    sha1.update(user.id.encode("utf-8"))
    sha1.update(b":")
    sha1.update(passwd.encode("utf-8"))
    if user.passwd != sha1.hexdigest():
        raise APIValueError("passwd", "Invalid password.")

    ret = web.Response()
    ret.set_cookie(
        COOKIE_NAME,
        user2cookie(user, 86400),
        max_age=86400,
        httponly=True
    )
    user.passwd = "******"
    ret.content_type = "application/json"
    ret.body = json.dumps(user, ensure_ascii=False).encode("utf-8")
    return ret


@get("/api/users")
async def api_get_users(*, page="1"):
    index = get_page_index(page)
    cnt = await User.findNumber("count(id)")
    p = Page(cnt, index)
    if cnt == 0:
        return dict(page=p, users=())
    users = await User.findAll(orderBy="created_at desc", limit=(p.offset, p.limit))
    for u in users:
        u.passwd = "******"
    return dict(page=p, users=users)


@post("/api/users")
async def api_register_user(*, email, name, passwd):
    if not name or not name.strip():
        raise APIValueError("name")
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError("email")
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError("passwd")

    users = await User.findAll("email=?", [email])
    if len(users) > 0:
        raise APIError("register: failied", "email", "Email is already in use.")
    id = next_id()
    sha1_passwd = "%s:%s" % (id, passwd)
    user = User(
        id=id,
        name=name.strip(),
        email=email,
        passwd=hashlib.sha1(sha1_passwd.encode("utf-8")).hexdigest(),
        image='http://www.gravatar.com/avatar/%s?d=mm&s=120' %
              hashlib.md5(email.encode('utf-8')).hexdigest()
    )
    await user.save()

    ret = web.Response()
    ret.set_cookie(
        COOKIE_NAME,
        user2cookie(user, 86400),
        max_age=86400,
        httponly=True
    )
    user.passwd = "******"
    ret.content_type = "application/json"
    ret.body = json.dumps(user, ensure_ascii=False).encode("utf-8")
    return ret


@get("/blog/{id}")
async def get_blog(id):
    blog = await Blog.find(id)
    comments = await Comment.findAll(
        "blog_id=?",
        [id],
        orderBy="created_at desc"
    )
    for c in comments:
        c.html_content = text2html(c.content)
    blog.html_content = markdown2.markdown(blog.content)
    return {
        "__template__": "blog.html",
        "blog": blog,
        "comments": comments
    }


@get("/api/blogs")
async def api_blogs(*, page="1"):
    page_index = get_page_index(page)
    cnt = await Blog.findNumber("count(id)")
    p = Page(cnt, page_index)
    if cnt == 0:
        return dict(page=p, blogs=())
    blogs = await Blog.findAll(orderBy="created_at desc", limit=(p.offset, p.limit))
    return dict(page=p, blogs=blogs)


@get("/api/blogs/{id}")
async def api_get_blog(*, id):
    blog = await Blog.find(id)
    return blog


@post("/api/blogs")
async def api_create_blog(request, *, name, summary, content):
    check_admin(request)

    if not name or not name.strip():
        raise APIValueError("name", "name cannot be empty")
    if not summary or not summary.strip():
        raise APIValueError("summary", "summary cannot be empty")
    if not content or not content.strip():
        raise APIValueError("content", "content cannot be empty")

    blog = Blog(
        user_id=request.__user__.id,
        user_name=request.__user__.name,
        user_image=request.__user__.image,
        name=name.strip(),
        summary=summary.strip(),
        content=content.strip()
    )
    await blog.save()
    return blog


@post("/api/blogs/{id}")
async def api_update_blog(id, request, *, name, summary, content):
    check_admin(request)
    blog = await Blog.find(id)

    if not name or not name.strip():
        raise APIValueError("name", "name cannot be empty")
    if not summary or not summary.strip():
        raise APIValueError("summary", "summary cannot be empty")
    if not content or not content.strip():
        raise APIValueError("content", "content cannot be empty")

    blog.name = name.strip()
    blog.summary = summary.strip()
    blog.content = content
    await blog.update()
    return blog


@post("/api/blogs/{id}/delete")
async def api_delete_blog(request, *, id):
    check_admin(request)
    blog = await Blog.find(id)
    await blog.remove()
    return dict(id=id)


@get("/api/comments")
async def api_comments(*, page="1"):
    index = get_page_index(page)
    cnt = await Comment.findNumber("count(id)")
    p = Page(cnt, index)
    if cnt == 0:
        return dict(page=p, comments=())
    comments = await Comment.findAll(orderBy="created_at desc", limit=(p.offset, p.limit))
    return dict(page=p, comments=comments)


@post("/api/blogs/{id}/comments")
async def api_create_comment(id, request, *, content):
    user = request.__user__
    if user is None:
        raise APIPermissionError("Please signin first.")
    if not content or not content.strip():
        raise APIValueError("content")

    blog = await Blog.find(id)
    if blog is None:
        raise APIResourceNotFoundError("Blog")
    comment = Comment(
        blog_id=blog.id,
        user_id=user.id,
        user_name=user.name,
        user_image=user.image,
        content=content.strip()
    )
    await comment.save()
    return comment


@post("/api/comments/{id}/delete")
async def api_delete_comments(id, request):
    check_admin(request)
    comment = await Comment.find(id)
    if comment is None:
        raise APIResourceNotFoundError("Comment")
    await comment.remove()
    return dict(id=id)


#########################################################
#   /manage/
#########################################################

@get("/manage/")
def manage():
    return "redirect:/manage/comments"


@get("/manage/blogs")
def manage_blogs(*, page="1"):
    return {
        "__template__": "manage_blogs.html",
        "page_index": get_page_index(page)
    }


@get("/manage/users")
def manage_users(*, page="1"):
    return {
        "__template__": "manage_users.html",
        "page_index": get_page_index(page)
    }


@get("/manage/comments")
def manage_comments(*, page="1"):
    return {
        "__template__": "manage_comments.html",
        "page_index": get_page_index(page)
    }


@get("/manage/blogs/create")
def manage_create_blog():
    return {
        "__template__": "manage_blog_edit.html",
        "id": "",
        "action": "/api/blogs"
    }


@get("/manage/blogs/edit")
def manage_edit_blog(*, id):
    return {
        "__template__": "manage_blog_edit.html",
        "id": id,
        "action": "/api/blogs/{}".format(id)
    }
