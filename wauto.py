# -*- coding: utf-8 -*-

import sys
sys.path.append('snsapi')
from functools import wraps
import json

import snsapi
from snsapi.snspocket import SNSPocket
from snsapi.snslog import SNSLog as logger
from lbucket import *

try:
    _wauto_conf = json.loads(open('conf/wauto.json').read())
except Exception, e:
    logger.warning("Load conf error: %s. Use default", e)
    _wauto_conf = {}
    _wauto_conf['priority'] = {
      'update': 5, 
      'home_timeline': 4,
      'forward': 3, 
      'reply': 3
    }
logger.debug("conf: %s", _wauto_conf)

''' 
Make the invokation from Python interpreter more convenient. 
Use synchronous calls. 
'''
def _dummy_decorator_generator(*args, **kwargs):
    def _dummy_decorator(func):
        return func
    return _dummy_decorator

if __name__ == '__main__':
    rate_limit = _dummy_decorator_generator

def cal_bucket(upperbound, period):
    '''
    Do conservative calculation to generate a bucket for SinaWeibo

    The limit is represented as ``x/y`` in the doc. 

    :param upperbound: x (in original scale)
    :param period: y (in seconds)
    '''
    # for safety
    ratio_capacity = 0.9
    ratio_init = 0.3
    upperbound = float(upperbound)
    period = float(period)
    fill_rate = upperbound / period
    tokens_max = upperbound * ratio_capacity
    tokens_init = upperbound * ratio_init
    return LeakyBucket(tokens_max, tokens_init, fill_rate)


class WeiboAutomator(object):
    '''Wrap common operations with rate limit facility
    '''

    # Most buckets are derived from Sina's offcial description [1]. 
    # The additional one 'wauto_snsapi' limits SNSAPI request rate globally
    # (avoid lower layer failure). 
    # 
    # Ref:
    #    * [1] http://open.weibo.com/wiki/Rate-limiting
    SINA_BUCKETS = [
            ('wauto_snsapi', LeakyBucket(1, 0, 0.5)),
            ('ip.hour.test_auth', cal_bucket(1000, 60*60)),
            ('user.hour.test_auth.total', cal_bucket(150, 60*60)),
            ('user.hour.test_auth.update', cal_bucket(30, 60*60)),
            ('user.hour.test_auth.reply', cal_bucket(60, 60*60)),
            ('user.hour.test_auth.follow', cal_bucket(60, 60*60)),
            ('user.day.test_auth.follow', cal_bucket(100, 60*60*24)),
            ]

    POLICY_GROUP = {}
    POLICY_GROUP['general'] = {
            'wauto_snsapi': 1, 
            'ip.hour.test_auth': 1,
            'user.hour.test_auth.total': 1
            }
    POLICY_GROUP['update'] = dict(POLICY_GROUP['general'], 
            **{'user.hour.test_auth.update': 1})
    POLICY_GROUP['reply'] = dict(POLICY_GROUP['general'], 
            **{'user.hour.test_auth.reply': 1})
    POLICY_GROUP['follow'] = dict(POLICY_GROUP['general'], 
            **{'user.hour.test_auth.follow': 1, 'user.day.test_auth.follow': 1})
    
    _log = lambda x: logger.debug('ret: %s', x)

    def __init__(self):
        super(WeiboAutomator, self).__init__()
        self.sp = SNSPocket()
        self.sp.load_config()
        self.sp.auth()
        # assign 'channel_name' as automator
        self.weibo = self.sp['automator'] 

        self.rlq = RateLimitQueue() 
        map(lambda t: self.rlq.add_bucket(t[0], t[1]), self.SINA_BUCKETS)

    # This implementation of dumps and loads are too simple. 
    # They do not work with some callback functions. 
    # I switch to 'dill'

    #def dumps(self):
    #    r = copy.deepcopy(self.rlq)
    #    for t in r._tasks:
    #        # First arg should be 'self' if do not operate our RLQ directly. 
    #        t.args = list(t.args)
    #        t.args.pop(0)
    #        t.func = marshal.dumps(t.func.func_code)
    #        t.callback = marshal.dumps(t.callback.func_code)
    #    return pickle.dumps(r)

    #def loads(self, s):
    #    r = pickle.loads(s)
    #    for t in r._tasks:
    #        t.args.insert(0, self)
    #        t.args = tuple(t.args)
    #        code_func = marshal.loads(t.func)
    #        t.func = types.FunctionType(code_func, globals())
    #        code_callback = marshal.loads(t.callback)
    #        t.callback = types.FunctionType(code_callback, globals())
    #    self.rlq = r

    #Original 'loads' 2
    #    #self.rlq._buckets = r._buckets
    #    #for t in r._tasks:
    #    #    code = marshal.loads(t.callback)
    #    #    t.callback = types.FunctionType(code, globals())
    #    #    t.args.insert(0, self)
    #    #    t.args = tuple(t.args)
    #    #    t.kwargs['callback'] = t.callback
    #    #    f = getattr(WeiboAutomator, t.func)
    #    #    # Execute the wrapped class method again to insert task
    #    #    f(*t.args, **t.kwargs)

    def run(self):
        return self.rlq.run()

    def clear_tasks(self):
        return self.rlq.clear_tasks()

    def get_uid(self):
        if hasattr(self, '_uid'):
            return self._uid
        else:
            ret = self.weibo.weibo_request('account/get_uid',
                    'GET',
                    {})
            return ret['uid']
         
    uid = property(get_uid)

    def rate_limit_status(self):
        ret = self.weibo.weibo_request('account/rate_limit_status',
                'GET',
                {})
        return ret

    @rate_limit(buckets=POLICY_GROUP['follow'], callback=_log)
    def follow(self, uid):
        ret = self.weibo.weibo_request('friendships/create',
                'POST',
                {'uid': uid})
        return ret

    @rate_limit(buckets=POLICY_GROUP['follow'], callback=_log)
    def follow_by_name(self, screen_name):
        ret = self.weibo.weibo_request('friendships/create',
                'POST',
                {'screen_name': screen_name})
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log, 
            priority=_wauto_conf['priority']['home_timeline'])
    def home_timeline(self, count=20):
        return self.weibo.home_timeline(count)

    @rate_limit(buckets=POLICY_GROUP['update'], callback=_log,
            priority=_wauto_conf['priority']['update'])
    def update(self, text):
        return self.weibo.update(text)

    @rate_limit(buckets=POLICY_GROUP['reply'], callback=_log,
            priority=_wauto_conf['priority']['reply'])
    def reply(self, status, text):
        if isinstance(status, snsapi.snstype.Message):
            statusID = status.ID
        else:
            statusID = status
        return self.weibo.reply(statusID, text)

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log,
            priority=_wauto_conf['priority']['forward'])
    def forward(self, status, text):
        return self.weibo.forward(status, text)

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def show(self, uid = None, screen_name = None):
        params = {}
        if not uid is None:
            params['uid'] = uid
        elif not screen_name is None:
            params['screen_name'] = screen_name
        else:
            params['uid'] = self.uid

        ret = self.weibo.weibo_request('users/show',
                'GET',
                params)
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def domain_show(self, url):
        '''Lookup user by personal url. 
        We will match and remove common weibo prefix. 

        :param url:
            e.g. 'http://weibo.com/xiena' --> url='xiena'
        '''
        import re
        pattern = re.compile('^http:\/\/.*weibo.com\/')
        url = re.sub(pattern, '', url)
        ret = self.weibo.weibo_request('users/domain_show',
                'GET',
                {'domain': url})
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def get_friends(self, uid=None, screen_name=None, count=200, cursor=None):
        params = {'count': count}

        if not uid is None:
            params['uid'] = uid
        elif not screen_name is None:
            params['screen_name'] = screen_name
        else:
            params['uid'] = self.uid

        if not cursor is None:
            params['cursor'] = cursor
        ret = self.weibo.weibo_request('friendships/friends',
                'GET',
                params)
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def get_friends_ids(self, uid=None, screen_name=None, count=5000, cursor=None):
        params = {'count': count}

        if not uid is None:
            params['uid'] = uid
        elif not screen_name is None:
            params['screen_name'] = screen_name
        else:
            params['uid'] = self.uid

        if not cursor is None:
            params['cursor'] = cursor
        ret = self.weibo.weibo_request('friendships/friends/ids',
                'GET',
                params)
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def get_followers(self, uid=None, screen_name=None, count=200, cursor=None):
        params = {'count': count}

        if not uid is None:
            params['uid'] = uid
        elif not screen_name is None:
            params['screen_name'] = screen_name
        else:
            params['uid'] = self.uid

        if not cursor is None:
            params['cursor'] = cursor
        ret = self.weibo.weibo_request('friendships/followers',
                'GET',
                params)
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def get_followers_ids(self, uid=None, screen_name=None, count=5000, cursor=None):
        params = {'count': count}

        if not uid is None:
            params['uid'] = uid
        elif not screen_name is None:
            params['screen_name'] = screen_name
        else:
            params['uid'] = self.uid

        if not cursor is None:
            params['cursor'] = cursor
        ret = self.weibo.weibo_request('friendships/followers/ids',
                'GET',
                params)
        return ret

    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def get_followers_active(self, uid=None, screen_name=None, count=200, cursor=None):
        params = {'count': count}

        if not uid is None:
            params['uid'] = uid
        elif not screen_name is None:
            params['screen_name'] = screen_name
        else:
            params['uid'] = self.uid

        if not cursor is None:
            params['cursor'] = cursor
        ret = self.weibo.weibo_request('friendships/followers/active',
                'GET',
                params)
        return ret

    # This Api is only for advanced app permission
    @rate_limit(buckets=POLICY_GROUP['general'], callback=_log)
    def search_topics(self, q, count=50, page=None):
        params = {'count': count}
        if not page is None:
            params['page'] = page
        ret = self.weibo.weibo_request('search/topics',
                'GET',
                params)
        return ret
    
if __name__ == '__main__':
    wa = WeiboAutomator()

# Previous tests to check the rate limit rules. 
#if __name__ == '__main__':
#    from time import sleep
#    import pprint
#    pp = pprint.PrettyPrinter(indent=4)
#    wa = WeiboAutomator()
#    pp.pprint(wa.rlq.get_buckets_info())
#    sleep(0.6)
#    pp.pprint(wa.rlq.get_buckets_info())
