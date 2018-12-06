import asyncio
import orm
from models import User, Blog, Comment
import logging

logging.basicConfig(level=logging.INFO)

async def test(loop):
	await orm.create_pool(
		loop, user="root", password="123456", db="awesome")

	u = User(name="Test2", email="test2@example.com", passwd="1234", image="about:blank")
	await u.save()

loop = asyncio.get_event_loop()
loop.run_until_complete(test(loop))
loop.close()