# -*- coding: utf-8 -*-

'''
Bot Utils
'''

import sys
sys.path.append('snsaspi')
from snsapi import snstype

import pickle

from datetime import datetime as dt

def refresh_my_info():
    wa.show(callback=lambda x: data.update({'myinfo': x}))
    data['friends'] = []
    data['followers'] = []
    if 'myinfo' in data:
        followers_count = data['myinfo']['followers_count']
        friends_count = data['myinfo']['friends_count']
    else:
        friends_count = 0
        followers_count = 0 
    def _exe(func, field, count, cursor):
        func(count=count, cursor=cursor, callback=lambda x: data[field].extend(x['users']))
    count = 200
    for i in range(0, int(friends_count / count) + 1):
        _exe(wa.get_friends, 'friends', count, i * count)
    for i in range(0, int(followers_count / count) + 1):
        _exe(wa.get_followers, 'followers', count, i * count)

def get_followers(uid, cursor):
    if not '_get_followers' in data:
        data['_get_followers'] = []
    wa.get_followers(uid, cursor=cursor, callback=lambda x: data['_get_followers'].extend(x['users']))

from extraction.userext import user_extract
from extraction.urlext import url_extract

def _ana_user(message):
    ul = user_extract(message.parsed.text)['users']
    return ul

def ana_users(message_list):
    '''
    Both Message or MessageList are supported
    '''
    if isinstance(message_list, list):
        ul = map(_ana_user, message_list)
        return reduce(lambda a,b: a + b, ul, [])
    else:
        return _ana_user(message_list)

def _filter_duplicate(fn_pickle, ml):
    try:
        sig = pickle.load(open(fn_pickle))
    except IOError:
        sig = set()
    ret = snstype.MessageList()
    for m in ml:
        s = m.digest()
        if not s in sig:
            sig.add(s)
            ret.append(m)
    pickle.dump(sig, open(fn_pickle, 'w'))
    return ret

FN_STORE_SIG_INTERSTING = 'store/sig.pickle'
FN_STORE_MSG_INTERSTING = 'store/msg.interesting'
def _store_msg(ml):
    '''
    Store with decuplication.

    :param ml: MessageList object
    '''
    l = _filter_duplicate(FN_STORE_SIG_INTERSTING, ml)
    with open(FN_STORE_MSG_INTERSTING, 'a') as fp:
        for m in l:
            s = m.digest()
            fp.write('===\nsig:%s\n---\n%s\n---\n' % (s, str(m)))


import os
import re
PATTERN_STORE_MSG = re.compile('(.*)\nsig:(.+)\n---\n(.+)\n---',  re.DOTALL)
FN_STORE_MSG_FORWARD = 'store/msg.forward'
def _forward_msg():
    try:
        content = open(FN_STORE_MSG_FORWARD).read()
        msgs = content.split('===')
    except IOError:
        msgs = []
    for m in msgs:
        r = PATTERN_STORE_MSG.search(m)
        if r:
            comment = r.groups()[0].strip()
            sig = r.groups()[1].strip()
            origin = r.groups()[2].strip()
            wa.forward(q.select_digest(sig)[0], comment.decode('utf-8'))
    if os.path.exists(FN_STORE_MSG_FORWARD):
        os.unlink(FN_STORE_MSG_FORWARD)

def _print(s):
    print s

PATTERN_COMMENT = re.compile('^\s*#.*$')
def cmd_from_file(fn):
    try:
        fn = open(fn)
        cmds = fn.read().split('\n')
    except IOError:
        cmds = []
    for c in cmds:
        c = c.strip()
        if not PATTERN_COMMENT.match(c):
            # Skip comments
            print c
            if len(c) > 0:
                eval(c)

def _when(predicate, func):
    '''
    :param predicate:
        e.g. 
        ``lambda hour, minute: minute==0``

    :param func:
        e.g. 
        ``lambda: wa.update('hello')``
    '''
    h, m = dt.now().hour, dt.now().minute
    if predicate(h, m):
        func()
