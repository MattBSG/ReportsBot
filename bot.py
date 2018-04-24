import asyncio
import json
import requests
import datetime
import time
import re

import discord
from pymongo import MongoClient

import constants

bot = discord.Client()
mclient = MongoClient(constants.mhost, username=constants.muser, password=constants.mpass)

@bot.event
async def on_ready():
	print(u"""
Discord Reporting Bot
Logged in as {}({})
\u00A9 Matthew Cohen 2018
----------------------------------------------------
""".format(bot.user, bot.user.id))

@bot.event
async def on_message(msg):
	message_content = msg.content.strip()
	if msg.author.bot:
		return

	# Splits message content into a list removing the command and prefix first
	if message_content.startswith(constants.prefix):
		command, *args = message_content.split()
		command = command[len(constants.prefix):].lower().strip()

	# Any message in the reporting channel that is not a command (won't do this in any other channel)
	elif msg.channel.id == constants.wz_submit:
		response = await bot.send_message(msg.channel, constants.redtick + ' <@{}>, This channel is only for making reports. Please do not use this channel for any discussion or conversation.'.format(msg.author.id))
		return await expire_msg(10, response, msg)

	else:
		return

	if command == 'report':
		try:
			player = args[0]
		except:
			# Arg out of range aka no args provided with command
			response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a player and reason')
			return await expire_msg(15, response, msg)
		try:
			request_handler('get', u'mc/player/{}'.format(player))['notFound']
			response = await bot.send_message(msg.channel, constants.redtick + ' That player has never joined the server')
			return await expire_msg(15, response, msg)
		except KeyError:
			# If this errors, the player in fact does exist. Weird way I know
			pass

		if msg.channel.id != constants.wz_submit and msg.author.id not in constants.devs:
			response = await bot.send_message(msg.channel, constants.redtick + ' You cannot do that here')
			return await expire_msg(15, response, msg)

		if not args[1]:
			response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a reason for the report')
			return await expire_msg(15, response, msg)

		reason = ''
		for arg in args[1:]:
			reason += '{} '.format(arg)

		history_list = lookup_puns(player)

		member = discord.utils.get(msg.server.members, display_name=player)

		# Really annoyingly convoluted for the thumbnail image. Essentially: (member with reported name is on discord -> avatar url OR else default avatar) otherwise (reporter avatar OR else default avatar)
		if member:
			if member.avatar_url:
				avatar = member.avatar_url

			else:
				avatar = member.default_avatar_url

		else:
			if msg.author.avatar_url:
				avatar = msg.author.avatar_url

			else:
				avatar = msg.author.default_avatar_url

		db = mclient.reports.cases
		case_num = mongo_inc()

		# Hardcoded db data to populate
		db_data = {
		'case': case_num,
		'avatar': avatar,
		'reporter': msg.author.id,
		'reporter_name' : '{}#{}'.format(msg.author.name, msg.author.discriminator),
		'reported': player,
		'reason': reason,
		'timestamp': int(time.time()),
		'closed': False,
		'close_reason': None,
		'closer': None,
		'closer_name': None,
		'late_notified': False
		}

		db_data['reported_discord'] = member.id if member else None

		escaped_reason = escape_links(reason)
		# Build embed and delete the invoking and response messages
		embed = discord.Embed(title=player, color=0xf6bf55, description='A report has been filed for **{}** by **{}#{}**. Once this has been reviewed you may close this report with `!resolve {} [reason]`'.format(player, msg.author.name, msg.author.discriminator, case_num), timestamp=datetime.datetime.utcnow())
		embed.add_field(name='Reason:', value=reason)
		embed.add_field(name='Past punishments:', value=history_list)
		embed.set_thumbnail(url=avatar)
		embed.set_footer(text='Case {}'.format(case_num))

		report_message = await bot.send_message(bot.get_channel(constants.wzstaff_reports), embed=embed)
		response = await bot.send_message(msg.channel, constants.greentick + ' Successfully submitted report against **{}** for **{}**! A staff member will review it as soon as possible. As soon as it\'s resolved, you will be notified of the result via DMs.'.format(player, escaped_reason))

		db_data['report_msg'] = report_message.id
		db.insert(db_data)

		return await expire_msg(600, response, msg)# 10 minutes
	
	elif command == 'resolve':
		for role in msg.author.roles:
			if role.id in constants.wzstaff_roles or msg.author.id in constants.devs:
				# We found a matching role, exit loop
				is_staff = True
				break

			is_staff = False

		if not is_staff or msg.server.id != constants.wzstaff and msg.author.id not in constants.devs:
			return

		try:
			case_num = int(args[0])

		except:
			# Will get thrown if the first arg is not a number
			response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a valid case ID and a reason.\nExample: `!resolve 27 Banned the player`')
			return await expire_msg(15, response, msg)

		try:
			str(args[1])

		except:
			# Thrown if the second arg or more does not exist
			response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a valid case ID and a reason.\nExample: `!resolve 27 Banned the player`')
			return await expire_msg(15, response, msg)

		reason = ''
		for arg in args[1:]:
			reason += '{} '.format(arg)

		db = mclient.reports.cases
		case_lookup = db.find_one({'case': case_num})
		# TODO: If a case does not exist raise an exception
		if not case_lookup:
			response = await bot.send_message(msg.channel, constants.redtick + ' That case does not exist.')
			return await expire_msg(15, response, msg)

		elif case_lookup['closed']:
			response = await bot.send_message(msg.channel, constants.redtick + ' That case was already closed for **{}**.'.format(case_lookup['close_reason']))
			return await expire_msg(15, response, msg)

		db.update_one({'case': case_num}, {'$set': {
				'close_reason': reason,
				'closed': True,
				'closer': msg.author.id,
				'closer_name': '{}#{}'.format(msg.author.name, msg.author.discriminator)
				}})
		selection = db.find_one({'case': case_num})

		for server in bot.servers:
			for member in server.members:
				if member.id == selection['reporter']:
					reporter = member
					break

		await resolve_edit_message(selection['report_msg'])

		try:
			await bot.send_message(reporter, 'Your report for **{}** has been reviewed by a staff member.\nComment: `{}`'.format(selection['reported'], selection['close_reason']))

		except:
			return await bot.send_message(msg.channel, constants.greentick + ' Successfully marked the report as resolved, however, I was unable to DM the reporter.')

		return await bot.send_message(msg.channel, constants.greentick + ' Successfully marked the report as resolved.')

	# TODO: Lookup command for case or player and the history

	elif command == 'dev':
	"""
	Developer command. I usually test functions through commands. I leave them in just in-case I'll ever use them again
	"""
		if msg.author.id not in constants.devs:
			return

		if args[0] == 'expire':
			# Expires the test message and invoking after 5 seconds
			message = await bot.send_message(msg.channel, 'Testing function :hourglass:')
			await expire_msg(5, message, msg)
			print(msg.id)

		elif args[0] == 'regex':
			# Testing the link escaping regex using the message you provide
			return await bot.send_message(msg.channel, escape_links(msg.content))

		elif args[0] == 'db':
			# Manually checks old reports. Should not be used since this was made before the loop was put in place
			return check_old()

		elif args[0] == 'msg':
			# Edits a report message with a provided hard coded id in the format after a resolve. Embed is missing as I was only testing it's use
			channel = bot.get_channel(constants.wzstaff_reports)
			message = await bot.get_message(channel, 'msg_id')
			await bot.edit_message(message, embed=embed)

		elif args[0] == 'resync':
			# Very dangerous. Iterates through the database and marks all unclosed cases as closed. Does not run normal resolve logic and operations
			db = mclient.reports.cases
			db2 = mclient.reports.cases
			selection = db.find({'closed': False})
			avatar = msg.author.default_avatar_url
			for case in selection:
				case_num = case['case']
				await resolve_edit_message(case['report_msg'], avatar)
				db2.update_one({'case': case_num}, {'$set': {
				'closed': True
				}})
			await bot.send_message(msg.channel, constants.greentick + ' Completed')

	elif msg.channel.id == constants.wz_submit:
		# Responds only in the reports submission channel.
		response = await bot.send_message(msg.channel, constants.redtick + ' Invalid command.')
		return await expire_msg(10, response, msg)

async def expire_msg(expiry, message, invoking=None):
	"""
	A function that deletes a message object and optionally an invoking message object after a provided time
	"""
	await asyncio.sleep(expiry)

	try:
		if invoking:
			await bot.delete_message(invoking)

	except:
		# The only real possible exception here is a discord Not Found error, prob someone deleted before timer ended
		pass

	try:
		await bot.delete_message(message)

	except:
		# The only real possible exception here is a discord Not Found error, prob someone deleted before timer ended
		pass

async def resolve_edit_message(id):
	"""
	Internally called to edit a resolved report's message to display as resolved with relevant information
	"""
	db = mclient.reports.cases
	case = db.find_one({'report_msg': id})

	embed = discord.Embed(title=case['reported'], color=0x3cf62a, description='A report was filed for **{}** by **{}**. This report was marked as resolved by {} at {} UTC.'.format(case['reported'], case['reporter_name'], case['closer_name'], datetime.datetime.utcnow()), timestamp=datetime.datetime.fromtimestamp(case['timestamp']))
	embed.add_field(name='Report reason:', value=case['reason'])
	embed.add_field(name='Resolve reason:', value=case['close_reason'])
	embed.add_field(name='Past punishments:', value=lookup_puns(case['reported']))
	embed.set_thumbnail(url=case['avatar'])
	embed.set_footer(text='Case {}'.format(case['case']))
	channel = bot.get_channel(constants.wzstaff_reports)
	message = await bot.get_message(channel, id)
	await bot.edit_message(message, embed=embed)


def lookup_puns(player):
	"""
	Returns a type(str) formated list of punishments on a given player (assumes already checked if they existed)
	"""
	p_history = request_handler('post', 'mc/player/punishments', {'name': player})['punishments']
	if not p_history:
		history_list = '*No previous punishments*'

	else:
		history_list = '\n'

		for pun in p_history:
			# Include date + punisher in future
			#if pun['punisher'] == None:
			#	issuer = 'Console'
			pun_type = '~~{}~~'.format(pun['type']) if pun['reverted'] else pun['type']
			history_list += '**{}** - {}\n'.format(pun_type, pun['reason'])

		return history_list

def request_handler(type, endpoint, data={}):
	"""
	A utility function for posting specific requests
	"""
	base = 'http://na2.minehut.com:3000/'
	headers = {'x-access-token': constants.wzkey}
	if type == 'get':
		r = requests.get(base + endpoint, headers=headers, json=data)
		r.raise_for_status()
		return r.json()

	elif type == 'post':
		r = requests.post(base + endpoint, headers=headers, json=data)
		r.raise_for_status()
		return r.json()

	else:
		raise TypeError('Invalid request type provided')

def mongo_inc():
	"""
	Used to find the next case id to use so they are incremental. Internal function only
	"""
	col = mclient.reports.cases
	if len(list(col.find())) is not 0:
		last_id = list(col.find({}).sort("case", -1).limit(1))
		return last_id[0]["case"] + 1

	else:
		return 0 + 1

def escape_links(text):
	"""
	Returns a provided string with links escaped for discord. i.e.: https://google.com -> <https://google.com>
	"""
	return re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', r'<\g<0>>', text)

async def check_old():
	"""
	A looped function to test if a report is older than a specified time (12hours) and remind staff if still open
	"""
	await bot.wait_until_ready()
	db = mclient.reports.cases
	notified = {}
	while not bot.is_closed:
		# Only run when asyncio loop is running (else exceptions)
		for case in db.find({'closed': False}):
			if (time.time() - case['timestamp']) >= 43200:
				# Report is older than 12 hours
				if not case['late_notified']:
					embed = discord.Embed(title=case['reported'], color=0xf6bf55, description='User **{}** filed a report over 12 hours ago against **{}**. Once this has been reviewed you may close this report with `!resolve {} [reason]`'.format(case['reporter_name'], case['reported'], case['case']), timestamp=datetime.datetime.fromtimestamp(case['timestamp']))
					embed.add_field(name='Reason:', value=case['reason'])
					embed.set_footer(text='Case {}'.format(case['case']))
					await bot.send_message(bot.get_channel(constants.wzstaff_discussion), ':exclamation: Report **{}** has been unresolved for 12 hours.\n\nThis is a courtesy reminder for <@&409429605708201995> and <@&405195413440954369>. Details attached:'.format(case['case']), embed=embed) # Hard coded role IDs for jr.mod and mod. TODO: don't do that
					db.update_one({'case': case['case']}, {'$set': {
					'late_notified': True
					}})
					
		await asyncio.sleep(5)

bot.loop.create_task(check_old())
bot.run(constants.discord_token)
