import logging
import configparser
import time
import json
from json import JSONDecodeError
from pprint import pprint

from beem.account import Account
from beem.blockchain import Blockchain
from beem.comment import Comment
from beem.steem import Steem


config = configparser.ConfigParser()
config.read('config.ini')

log = logging.getLogger(__name__)
log.setLevel(level='INFO')

s = Steem(keys=config['GENERAL']['posting_key'], node='https://api.steemit.com', nobroadcast=config.getboolean('GENERAL', 'testing'), bundle=True)
a = Account(account=config['GENERAL']['acc_name'], steem_instance=s)
b = Blockchain(steem_instance=s)


def vote(c):
    if config['GENERAL']['acc_name'] not in c.get_votes():  # check if account has already voted this post
        penalty = c.get_curation_penalty()
        if penalty > 0.0:
            print('    FOUND post: ' + c.permlink)
            wait = penalty * config.getint('VOTER', 'vote_after_minutes') * 60
            print('    WAITING ' + str(wait) + ' seconds')
            time.sleep(wait)

            comment_body = ''
            if config.getboolean('VOTER', 'write_comment'):
                with open(file=config['VOTER']['comment_file'], mode='rb') as file:  # loading comment text
                    comment_body = file.read().decode('UTF-8')
                    print('Loaded comment text.')

            try:
                c.upvote(weight=config.getfloat('VOTER', 'vote_weight'), voter=config['GENERAL']['acc_name'])  # Finally vote post and leave a comment
                if config.getboolean('VOTER', 'write_comment'):
                    c.reply(body=comment_body, author=config['GENERAL']['acc_name'])
                pprint(s.broadcast())
                print('      VOTED ' + c.permlink)
                return True
            except Exception as err:
                log.warning('ERROR: ' + str(err))
                log.warning('      Didn\'t vote ' + c.permlink)

        else:
            print('      Post is edit after 30 minutes')
    else:
        print('      Post already voted.')
    return False


def check_criteria(author, perm):  # vote the post
    permlink = author + '/' + perm
    c = Comment(authorperm=permlink, steem_instance=s)

    # ===== Users whitelist ==================================================================================================================================
    try:
        with open(file=config['VOTER']['whitelist_users'], mode='r') as file:  # loading whitelisted usernames
            check_list = file.read().split('\n')
            print('Loaded whitelisted users.')
            if author in check_list:  # cancelling checking if author is on whitelist
                print('    Bypassed filtering because author is whitelisted.')
                return vote(c)
    except FileNotFoundError:
        log.exception('Failed loading whitelisted users. Continuing without checking.')

    # ===== Post length ======================================================================================================================================
    if len(c.body.replace('-', '').replace('*', '').replace('_', '').split()) < config.getint('VOTER', 'minimum_post_length'):
        print('    Dumped because of insufficient length.')
        return False

    # ===== Users blacklist ==================================================================================================================================
    try:
        with open(file=config['VOTER']['blacklist_users'], mode='r') as file:  # loading banned usernames
            check_list = file.read().split('\n')
            print('Loaded banned users.')
            if author in check_list:  # cancelling vote if author is on blacklist
                print('    Dumped because author is banned.')
                return False
    except FileNotFoundError:
        log.exception('Failed loading banned users. Continuing without checking.')

    # ===== Words blacklist ==================================================================================================================================
    try:
        with open(file=config['VOTER']['blacklist_words'], mode='rb') as file:  # loading banned words
            check_list = file.read().decode('UTF-8').split('\n')
            print('Loaded banned words.')
            post_body = c.body.replace(',', ' ').replace('.', ' ').replace('!', ' ').replace('?', ' ').replace('"', ' ').replace("'", ' ').split()
            for check in check_list:  # cancelling vote if banned words are used
                if check in post_body:
                    print('    Dumped because at least one word used is banned.')
                    return False
    except FileNotFoundError:
        log.exception('Failed loading banned words. Continuing without checking.')

    # ===== Author reputation ================================================================================================================================
    if Account(account=author, steem_instance=s).get_reputation() < config.getfloat('VOTER', 'minimum_author_rep'):  # gets dumped if author rep is too low
        print('    Dumped for author reputation too low.')
        return False

    # ===== Banned tags ======================================================================================================================================
    try:
        tags = c.json_metadata['tags']
        for check in config['VOTER']['banned_tags'].replace(' ', '').split(','):  # scanning for banned tags
            if check in tags:
                print('\n    Dumped because of banned tags.\n')
                return False
    except KeyError as err:
        log.warning('\n    No tags on this post. (2)\n      ' + str(err))
        return False

    return vote(c)


def scan():
    counter = 0
    for post in b.stream(opNames=['comment']):  # scan for posts
        try:
            if post['parent_author'] == '':
                counter += 1
                print('\r' + str(counter), end=' scanned posts.', flush=True)
                tags = json.loads(post['json_metadata'])['tags']

                for check in config['VOTER']['voted_tags'].replace(' ', '').split(','):  # scanning for wanted tags in posts
                    if check in tags:
                        print('\n  In block ' + str(post['block_num']))
                        if check_criteria(post['author'], post['permlink']):  # Vote if selected tags are used
                            break
                        counter = 0
                else:
                    continue
                break

        except JSONDecodeError as err:  # catching exceptions
            log.warning('\n  JSON Failure :\n    ' + str(err))
        except KeyError as err:
            log.warning('\n  No tags on post. (1)\n    ' + str(err))
        except Exception as err:
            log.warning('\n  A really strange error occured...\n    ' + str(err))


if __name__ == '__main__':  # wait for enough voting power, then search for posts
    while True:
        a.refresh()
        vp = a.get_voting_power()
        print(a.name+' has '+str(vp))
        if vp > config.getint('VOTER', 'min_vp'):
            print('VP is over ' + config['VOTER']['min_vp'] + '%\n')
            try:
                scan()
            except Exception as e:
                log.warning('Scan failed. Error:\n' + str(e))
        else:
            time.sleep(config.getint('VOTER', 'check_vp_interval'))
        config.read('config.ini')
