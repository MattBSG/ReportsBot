import asyncio
import datetime
import logging
import re
import time
import requests

import discord
from pymongo import MongoClient

import constants

bot = discord.Client()
mclient = MongoClient(constants.mhost, username=constants.muser, password=constants.mpass)

# Debug logging for discord.py saved in logs/ formated as "starting epoche"-discord.log
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='logs/{}-discord.log'.format(int(time.time())), encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

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

    # Any message in the reporting channels that is not a command (won't do this in any other channel)
    elif msg.channel.id == constants.wz_submit or msg.channel.id == constants.wz_appeals:
        response = await bot.send_message(msg.channel, constants.redtick + ' <@{}>, This channel is only for using commands (see the topic and pinned message if you are confused). Please do not use this channel for any discussion or conversation.'.format(msg.author.id))
        return await expire_msg(15, response, msg)

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
            response = await bot.send_message(msg.channel, constants.redtick + ' The provided player has never joined the server')
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
        case_num = mongo_inc('cases')

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
        embed = discord.Embed(title=player, color=0xf6bf55, description='A report has been filed for **{}** by **{}#{}**. Once this has been reviewed you may close this report with `!close {} [reason]`'.format(player, msg.author.name, msg.author.discriminator, case_num), timestamp=datetime.datetime.utcnow())
        embed.add_field(name='Reason:', value=reason)
        embed.add_field(name='Past punishments:', value=history_list)
        embed.set_thumbnail(url=avatar)
        embed.set_footer(text='Case {}'.format(case_num))

        report_message = await bot.send_message(bot.get_channel(constants.wzstaff_reports), embed=embed)
        response = await bot.send_message(msg.channel, constants.greentick + ' Successfully submitted report against **{}** for **{}**! A staff member will review it as soon as possible. As soon as it\'s resolved you will be notified of the result via DMs.'.format(player, escaped_reason))

        db_data['report_msg'] = report_message.id
        db.insert(db_data)

        return await expire_msg(600, response, msg)# 10 minutes

    elif command in ['appeal', 'appeals']:
        example = 'Example:\n`!appeal MattBSG ban I am very sorry about my actions on the server and wish to be allowed to come back and enjoy Warzone again. Etc.`'

        if msg.channel.id not in [constants.wzstaff_discussion, constants.wz_appeals]:
            if msg.author.id not in constants.devs:
                response = await bot.send_message(msg.channel, constants.redtick + ' You cannot do that here')
                return await expire_msg(15, response, msg)

        # If an exception is raised for any of the following try statements, the arg is invalid and must be handled
        try:
            if args[0] in ['accept', 'deny', 'approve']:
                await appeals_update(args[0], args, msg)
                return

            else:
                player = args[0]

        except IndexError:
            response = await bot.send_message(msg.channel, constants.redtick + ' You must provide the Minecraft IGN whose punishment you are appealing for. ' + example)
            return await expire_msg(15, response, msg)

        try:
            request_handler('get', u'mc/player/{}'.format(player))['notFound']
            response = await bot.send_message(msg.channel, constants.redtick + ' The provided player has never joined the server')
            return await expire_msg(15, response, msg)

        except:
            pass

        try:
            pun_type = args[1].lower()
            if pun_type not in ['mute', 'ban']:
                response = await bot.send_messsage(msg.channel, constants.redtick + ' You must provide a proper punishment type you are appealing. Either "mute" or "ban". ' + example)
                return await expire_msg(15, response, msg)

        except:
            response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a punishment type that you are appealing for. Either "mute" or "ban". ' + example)
            return await expire_msg(15, response, msg)

        try:
            reason = args[2]
            for arg in args[3:]:
                reason += ' ' + arg

        except:
            response = await bot.send_message(msg.channel, constants.redtick + ' You must provide an in-depth reason on why you are appealing. ' + example)
            return await expire_msg(15, response, msg)

        if len(reason) > 1800:
            # Built in check to make sure it is not way longer than it needs to be, getting near character limit
            response = await bot.send_message(msg.channel, constants.redtick + ' Your reason is too long, please trim it down and resubmit. Your message will be deleted in 30 seconds if you need to save it')
            return await expire_msg(30, response, msg)

        puns = request_handler('post', 'mc/player/punishments', {'name': player})['punishments']

        if not puns:
            response = await bot.send_message(msg.channel, constants.redtick + ' There are no punishments on record to appeal for')
            return await expire_msg(15, response, msg)

        # It is possible for a player to be double punished. Appealing should undo ALL active counts of the appealed punishment type
        active_list = []

        for punishment in puns:
            if punishment['type'] == pun_type.upper() and punishment['active']:
                active_list.append(punishment)
        
        if not active_list:
            response = await bot.send_message(msg.channel, constants.redtick + ' There are no active punishments of this type to appeal for')
            return await expire_msg(15, response, msg)

        # Check if player is linked. If not await a Sr. Mod approval before other staff can review
        needs_verification = True
        for role in msg.author.roles:
            if role.id == constants.linked and msg.author.nick == player:
                needs_verification = False
                break

        if needs_verification and pun_type == 'mute' and msg.author.id not in constants.devs:
            response = await bot.send_message(msg.channel, constants.redtick + ' You are currently trying to appeal a mute and your Minecraft account is not linked. Please join Warzone and run `/discord link` and appeal again.'\
                ' If you are also banned, please appeal your ban first.')
            return await expire_msg(30, response, msg)

        db = mclient.reports.appeals
        case_num = mongo_inc('appeals')
        avatar = msg.author.avatar_url if msg.author.avatar_url else msg.author.default_avatar_url
        tag = '{}#{}'.format(msg.author.name, msg.author.discriminator)

        # Hardcoded db data to populate
        db_data = {
            'case': case_num,
            'avatar': avatar,
            'appealer': msg.author.id,
            'appealer_name' : tag,
            'player': player,
            'reason': reason,
            'timestamp': int(time.time()),
            'closed': False,
            'close_reason': None,
            'closer': None,
            'closer_name': None,
            'late_notified': False,
            'approver_name': None,
            'pun_type': pun_type,
            'active_puns': active_list,
            'accepted': None,
            'not_verified': needs_verification
        }

        # Construct embed
        if needs_verification:
            embed = discord.Embed(title='Admin or Sr. Mod approval needed', color=0xfa2024, description='Appeal for **{}** created by **{}** has been flagged for being suspicious (User is not discord linked). To mark this as not spam, an Admin or Sr. Mod must run `!appeals approve {}` otherwise the appeal will be discarded soon'.format(player, tag, case_num), timestamp=datetime.datetime.utcnow())
            embed.add_field(name='Appeal reason:', value=reason)
            embed.set_footer(text='Appeal {}'.format(case_num))
            
        else:
            active_puns = ''
            for pun in active_list:
                punisher = 'Console' if pun['punisher'] == None else pun['punisherLoaded']['name']
                pun_type = 'banned' if pun_type == 'ban' else 'muted'
                issued = datetime.datetime.fromtimestamp(int((pun['issued'] / 1000))).strftime('%d/%m/%Y') # Imperial time, sorry
                expires = 'Forever' if pun['expires'] == -1 else datetime.datetime.fromtimestamp(int((pun['expires']) / 1000)).strftime('%d/%m/%y')
                active_puns += '`{}` - `{}`: {} **{}** for **{}**\n'.format(issued, expires, punisher, pun_type, pun['reason'])

            embed = discord.Embed(title=player, color=0xf6bf55, description='**{}** has submitted an appeal for account **{}**. Once the appeal is ready to be acted upon please run either `!appeals accept {} [reason]` or `!appeals deny {} [reason]`'.format(tag, player, case_num, case_num), timestamp=datetime.datetime.fromtimestamp(int(time.time())))
            embed.add_field(name='Appeal reason:', value=reason)
            embed.add_field(name='Active punishments:', value=active_puns)
            embed.add_field(name='All punishments:', value=lookup_puns(player))
            embed.set_thumbnail(url=avatar)
            embed.set_footer(text='Appeal {}'.format(case_num))

        appeal = await bot.send_message(bot.get_channel(constants.wzstaff_appeals), embed=embed)
        db_data['appeal_msg'] = appeal.id

        response = await bot.send_message(msg.channel, constants.greentick + ' Your appeal has been submitted, as soon as it\'s reviewed you will be notified of the result via DMs.')
        db.insert_one(db_data)
        return await expire_msg(30, response, msg)
        
    elif command == 'close':
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

        if args[0] == 'ping':
            # Testing the roundtrip latency
            bot_msg = await bot.send_message(msg.channel, ':hourglass: Measuring latency response time...')
            diff = bot_msg.timestamp - msg.timestamp
            await bot.edit_message(bot_msg, 'Pong! Roundtrip was {:.1f}ms.'.format(1000*diff.total_seconds()))
        
        if args[0] == 'reopen':
            try:
                str(args[1])
            except:
                return await bot.send_message(msg.channel, 'You need to specify an appeal')
            message = await bot.send_message(msg.channel, 'This is likely to break something. Confirming you want to __reopen__ appeal **{}**?'.format(args[1]))
            await bot.add_reaction(message, '✅')
            react = await bot.wait_for_reaction(['✅'], message=message, timeout=10, user=msg.author)

            if not react:
                return await bot.edit_message(message, 'Request timed out waiting for reaction')
            
            try:
                db = mclient.reports.appeals
                db.update_one({'case': args[1]}, {'$set': {
                        'closed': False
                    }})
            except Exception as e:
                return await bot.edit_message(message, 'Exception with database: {}'.format(e))
            
            await bot.clear_reactions(message)
            return await bot.edit_message(message, 'Appeal {} has been reopened.'.format(args[1]))

        if args[0] == 'rename':
            # Updates the name for the bot account
            try:
                await bot.edit_profile(username=args[1])
                await bot.send_message(msg.channel, ':ok_hand:')
            except Exception as e:
                await bot.send_message(msg.channel, constants.redtick + ' I encountered an error setting my name. Output:\n{}'.format(e))

        if args[0] == 'expire':
            # Expires the test message and invoking after 5 seconds
            message = await bot.send_message(msg.channel, 'Testing function :hourglass:')
            return await expire_msg(5, message, msg)

        elif args[0] == 'regex':
            # Testing the link escaping regex using the message you provide
            return await bot.send_message(msg.channel, escape_links(msg.content))

        elif args[0] == 'db':
            # Manually checks old reports. Should not be used since this was made before the loop was put in place
            return check_old()
        
        elif args[0] == 'puns':
            # Return the json of puns for a given player
            return await bot.send_message(msg.channel, 'Here you go:\n\n{}'.format(lookup_puns(args[1])))

        elif args[0] == 'roles':
            role_list = ''
            for role in msg.server.roles:
                role_list += '{} - {}\n'.format(role.name, role.id)
            return await bot.send_message(msg.channel, role_list)

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
                await resolve_edit_message(case['report_msg'])
                db2.update_one({'case': case_num}, {'$set': {
                    'closed': True
                }})
            await bot.send_message(msg.channel, constants.greentick + ' Completed')

    else:
        return

async def appeals_update(command, args, msg):
    """
    Function that handles staff approvals, acceptances, or denials of appeals
    """
    is_staff = False
    for role in msg.author.roles:
        if role.id in constants.wzstaff_roles:
            is_staff = True
            break

    if not is_staff:
        response = await bot.send_message(msg.channel, constants.redtick + ' You do not have permission to run that command')
        return await expire_msg(15, response, msg)

    db = mclient.reports.appeals

    try:
        appeal_id = int(args[1])
        
    except:
        response = await bot.send_message(msg.channel, constants.redtick + ' You must provide an valid appeal number')
        return await expire_msg(15, response, msg)

    appeal = db.find_one({'case': appeal_id})

    if not appeal:
        response = await bot.send_message(msg.channel, constants.redtick + ' An appeal with that ID does not exist')
        return await expire_msg(15, response, msg)

    if command == 'approve':
        # Approve an appeal to be reviewed by staff
        is_authed = False
        for role in msg.author.roles:
            if role.id in constants.srstaff:
                is_authed = True
                break
        
        if not is_authed:
            return await bot.send_message(msg.channel, constants.redtick + ' This command can only be run by an Admin or Sr. Mod')
        
        case_num = appeal['case']
        if appeal['not_verified'] != True:
            return await bot.send_message(msg.channel, constants.redtick + ' This appeal is not awaiting approval')
        await update_appeal_edit(appeal_id, 'approval')
        db.update_one({'case': case_num}, {'$set': {
            'not_verified': False
        }})
        return await bot.send_message(msg.channel, constants.greentick + ' Successfully approved the appeal. It is now unlocked for other staff to review')

    if appeal['closed']:
        response = await bot.send_message(msg.channel, constants.redtick + ' That appeal has already been closed')
        return await expire_msg(15, response, msg)
    
    if appeal['not_verified']:
        response = await bot.send_message(msg.channel, constants.redtick + ' That appeal is awaiting an approval from an Admin or Sr. Mod')
        return await expire_msg(15, response, msg)

    

    elif command == 'accept':
        # Accept an appeal submitted by a user
        try:
            reason = args[2]
            for arg in args[3:]:
                reason += ' ' + arg
        
        except:
            response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a reason for this action')
            return expire_msg(15, response, msg)

        for server in bot.servers:
                for member in server.members:
                    if member.id == appeal['appealer']:
                        appealer = member
                        break

        accepter = u'{}#{}'.format(msg.author.name, msg.author.discriminator)
        case_num = appeal['case']

        for pun in appeal['active_puns']:
            try:
                r = request_handler('post', 'mc/player/revert_punishment', {'id': pun['_id']})
                if r['punishment']['reverted'] != True:
                    raise KeyError('Punishment returned unreverted after request')
            
            except Exception as e:
                print(u'An exception was raised while reverting a punishment.\n\nServer: {}\nCommand: {}\nOutput: {}'.format(msg.server.name, command, e))
                return await bot.send_message(msg.channel, constants.redtick + ' An error occurred while processing the command. If this continues please contact a Sr. Mod or Admin')

        db.update_one({'case': case_num}, {'$set': {
            'closer': msg.author.id,
            'closer_name': accepter,
            'close_reason': reason,
            'accepted': True,
            'closed': True
        }})

        await update_appeal_edit(case_num, 'accepted', reason)

        try:
            await bot.send_message(appealer, 'Your __{}__ appeal for Warzone has been **accepted** by **{}** and was reverted.\n\nComments: `{}`'.format(appeal['pun_type'], accepter, reason))

        except:
            return await bot.send_message(msg.channel, constants.greentick + ' The appeal was successfully accepted and punishments have reverted, but I was unable to notify the appealer through DMs')
        
        return await bot.send_message(msg.channel, constants.greentick + ' The appeal was successfully accepted and punishments have been reverted')
    
    elif command == 'deny':
        try:
            reason = args[2]
            for arg in args[3:]:
                reason += ' ' + arg
        
        except:
            response = await bot.send_message(msg.channel, constants.redtick + ' You must provide a reason for this action')
            return expire_msg(15, response, msg)
        
        for server in bot.servers:
                for member in server.members:
                    if member.id == appeal['appealer']:
                        appealer = member
                        break

        accepter = u'{}#{}'.format(msg.author.name, msg.author.discriminator)
        case_num = appeal['case']

        db.update_one({'case': case_num}, {'$set': {
            'closer': msg.author.id,
            'closer_name': accepter,
            'close_reason': reason,
            'accepted': False,
            'closed': True
        }})
        
        await update_appeal_edit(case_num, 'denied', reason)

        try:
            await bot.send_message(appealer, 'Your __{}__ appeal for Warzone has been **denied** by **{}** and will stand.\n\nComments: `{}`'.format(appeal['pun_type'], accepter, reason))

        except:
            return await bot.send_message(msg.channel, constants.greentick + ' The appeal was successfully denied, but I was unable to notify the appealer through DMs')
        
        return await bot.send_message(msg.channel, constants.greentick + ' The appeal was successfully denied')


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
    return await bot.edit_message(message, embed=embed)

async def update_appeal_edit(id, type, status=None):
    """
    Internally called to edit an appeal message to display being approved or accepted/denied
    """
    db = mclient.reports.appeals
    appeal = db.find_one({'case': id})

    active_puns = ''
    for pun in appeal['active_puns']:
        punisher = 'Console' if pun['punisher'] == None else pun['punisherLoaded']['name']
        pun_type = 'banned' if appeal['pun_type'] == 'ban' else 'muted'
        issued = datetime.datetime.fromtimestamp(int((pun['issued'] / 1000))).strftime('%d/%m/%Y') # Imperial time, sorry
        expires = 'Forever' if pun['expires'] == -1 else datetime.datetime.fromtimestamp(int((pun['expires']) / 1000)).strftime('%d/%m/%y')
        active_puns += '`{}` - `{}`: {} **{}** for **{}**\n'.format(issued, expires, punisher, pun_type, pun['reason'])

    if type == 'approval':
        embed = discord.Embed(title=appeal['player'], color=0xf6bf55, description='**{}** has submitted an appeal for account **{}**. Once the appeal is ready to be acted upon please run either `!appeals accept {} [reason]` or `!appeals deny {} [reason]`'.format(appeal['appealer_name'], appeal['player'], appeal['case'], appeal['case']), timestamp=datetime.datetime.fromtimestamp(appeal['timestamp']))
        embed.add_field(name='Appeal reason:', value=appeal['reason'])
        embed.add_field(name='Active punishments:', value=active_puns)
        embed.add_field(name='All punishments:', value=lookup_puns(appeal['player']))
        embed.set_thumbnail(url=appeal['avatar'])
        embed.set_footer(text='Appeal {}'.format(id))

        channel = bot.get_channel(constants.wzstaff_appeals)
        message = await bot.get_message(channel, appeal['appeal_msg'])
        return await bot.edit_message(message, embed=embed)

    elif type == 'accepted':
        embed = discord.Embed(title=appeal['player'], color=0x3cf62a, description='**{}** submitted an appeal for account **{}**. This appeal was marked as __accepted__ by {} at {} UTC.'.format(appeal['appealer_name'], appeal['player'], appeal['closer_name'], datetime.datetime.utcnow()), timestamp=datetime.datetime.fromtimestamp(appeal['timestamp']))
        embed.add_field(name='Appeal reason:', value=appeal['reason'], inline=True)
        embed.add_field(name='Appeal reviewer', value='**{}** reviewed this appeal with comment: *{}*'.format(appeal['closer_name'], status))
        embed.add_field(name='All punishments:', value=lookup_puns(appeal['player']))
        embed.set_thumbnail(url=appeal['avatar'])
        embed.set_footer(text='Appeal {}'.format(id))

        channel = bot.get_channel(constants.wzstaff_appeals)
        message = await bot.get_message(channel, appeal['appeal_msg'])
        return await bot.edit_message(message, embed=embed)
    
    elif type == 'denied':
        embed = discord.Embed(title=appeal['player'], color=0x1594f2, description='**{}** submitted an appeal for account **{}**. This appeal was marked as __denied__ by {} at {} UTC.'.format(appeal['appealer_name'], appeal['player'], appeal['closer_name'], datetime.datetime.utcnow()), timestamp=datetime.datetime.fromtimestamp(appeal['timestamp']))
        embed.add_field(name='Appeal reason:', value=appeal['reason'], inline=True)
        embed.add_field(name='Appeal reviewer', value='**{}** reviewed this appeal with comment: *{}*'.format(appeal['closer_name'], status))
        embed.add_field(name='All punishments:', value=lookup_puns(appeal['player']))
        embed.set_thumbnail(url=appeal['avatar'])
        embed.set_footer(text='Appeal {}'.format(id))

        channel = bot.get_channel(constants.wzstaff_appeals)
        message = await bot.get_message(channel, appeal['appeal_msg'])
        return await bot.edit_message(message, embed=embed)
        # Finish this, more checks like if already closed. etc and polishing
    else:
        raise KeyError('Appeal edit provided with invalid type. This is a programming error')

def lookup_puns(player):
    """
    Returns a type(str) formated list of punishments on a given player (assumes already checked if they existed)
    """
    p_history = request_handler('post', 'mc/player/punishments', {'name': player})['punishments']
    if not p_history:
        history_list = '*No previous punishments*'

    else:
        history_list = '\n'

        for pun in p_history[::-1]:
            # Include date + punisher in future
            #if pun['punisher'] == None:
            #   issuer = 'Console'
            pun_type = '~~{}~~'.format(pun['type']) if pun['reverted'] else pun['type']
            history_list += '**{}** - {}\n'.format(pun_type, pun['reason'])

        return history_list

def request_handler(type, endpoint, data={}):
    """
    A utility function for posting specific requests
    """
    base = constants.wzhost
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

def mongo_inc(collection):
    """
    Used to find the next case id to use so they are incremental. Internal function only
    """
    col = mclient.reports[collection]
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
    A looped function to test different conditions for appeals and reports
    """
    await bot.wait_until_ready()
    #import calendar
    reports = mclient.reports.cases
    #appeals = mclient.reports.appeals
    while not bot.is_closed:
        # Only run when asyncio loop is running (else exceptions). TODO: integrate appeals reminders here too
        for case in reports.find({'closed': False}):
            # Tests if a report is older than a set time and sends a staff reminder
            if (time.time() - case['timestamp']) >= 43200:
                # Report is older than 12 hours
                if not case['late_notified']:
                    embed = discord.Embed(title=case['reported'], color=0xf6bf55, description='User **{}** filed a report over 12 hours ago against **{}**. Once this has been reviewed you may close this report with `!resolve {} [reason]`'.format(case['reporter_name'], case['reported'], case['case']), timestamp=datetime.datetime.fromtimestamp(case['timestamp']))
                    embed.add_field(name='Reason:', value=case['reason'])
                    embed.set_footer(text='Case {}'.format(case['case']))
                    await bot.send_message(bot.get_channel(constants.wzstaff_discussion), ':exclamation: Report **{}** has been unresolved for 12 hours.\n\nThis is a courtesy reminder for <@&409429605708201995> and <@&405195413440954369>. Details attached:'.format(case['case']), embed=embed) # Hard coded role IDs for jr.mod and mod. TODO: don't do that
                    reports.update_one({'case': case['case']}, {'$set': {
                        'late_notified': True
                    }})
        
        # On hold until timezone stuff is worked out with API
        #for appeal in appeals.find({'closed': False}):
        #   # Test if an appeal has been reverted in-game while open
        #   tracked_puns = []
        #   for pun in appeal['active_puns']:
        #       tracked_puns.append(pun['_id'])
            
        #   try:
        #       # We can safely ignore (if there are multiple of same type pun) if one is reverted and at least one is active
        #       for punishment in request_handler('post', 'mc/player/punishments', {'name': appeal['player']})['punishments']:
        #           if punishment['_id'] in tracked_puns:
        #               print('tracked')
        #               if punishment['reverted']:
        #                   print('expired!')
                        
        #               elif punishment['expires'] != -1 and punishment['expires'] < calendar.timegm(time.gmtime()):
        #                   print('expired! (timer)')

        #   except Exception as e:
        #       print('Unexpected exception running expired appeal loop: {}'.format(e))
        await asyncio.sleep(5)

bot.loop.create_task(check_old())
bot.run(constants.discord_token)
