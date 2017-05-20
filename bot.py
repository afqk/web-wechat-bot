# -*- coding: utf-8 -*-
import ast
import logging
import random
import time
from xml.etree.ElementTree import fromstring

import requests
from qrcode.main import QRCode

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


# noinspection SpellCheckingInspection,PyTypeChecker
class WebWeChatBot(object):
    def __init__(self):
        self.s = requests.session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.96 Safari/537.36',
            'Referer': 'https://wx2.qq.com/'
        }
        self.s.headers.update(self.headers)
        self.wx = {
            'lang': 'zh_CN',
        }
        self.qrlogin_uuid = None

    def login(self):
        if self.qrlogin_uuid is None:
            self.qrlogin_uuid = self._get_qrlogin_uuid()
        qr = QRCode(border=2)
        qr.add_data('https://login.weixin.qq.com/l/{}'.format(self.qrlogin_uuid))
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        self._start_login()

    @property
    def timestamp(self):
        return int(round(time.time() * 1000))

    @property
    def device_id(self):
        return 'e{}'.format(int(random.random() * 10 ** 15))

    def _get_qrlogin_uuid(self):
        jslogin = 'https://login.wx.qq.com/jslogin'
        r = self.s.get(jslogin, params={
            'appid': 'wx782c26e4c19acffb',
            'fun': 'new',
        })
        qrlogin_uuid = None
        r_txt = r.content.decode('utf-8')
        if r.ok and 'window.QRLogin.uuid' in r_txt:
            qrlogin_uuid = r_txt.split('"')[1]
            log.info('QRLogin uuid --> {}'.format(qrlogin_uuid))
        return qrlogin_uuid

    def _start_login(self):
        while 1:
            url = 'https://login.wx2.qq.com/cgi-bin/mmwebwx-bin/login'
            r = self.s.get(url, params={'uuid': self.qrlogin_uuid, 'tip': 0, '_': self.timestamp})
            r_txt = r.content.decode('utf-8')
            if 'window.code=200' not in r_txt:
                log.info('Wait for login: --> {}'.format(r_txt))
            else:
                redirect_uri = r_txt[r_txt.find('https'):r_txt.find('";')]
                r = self.s.get(redirect_uri, params={'fun': 'new', 'version': 'v2'})
                r_txt = r.content.decode('utf-8')
                if not r.ok:
                    log.warning('login failed: {}'.format(r_txt))
                    return
                root = fromstring(r_txt)
                for c in root:
                    self.wx[c.tag] = c.text
                self._web_wx_init()
                return

    def _web_wx_init(self):
        log.info('start web wx init...')
        url = 'https://wx2.qq.com/cgi-bin/mmwebwx-bin/webwxinit'
        self.s.headers.update({'Content-Type': 'application/json;charset=UTF-8'})
        r = self.s.post(url, params={'pass_ticket': self.wx['pass_ticket']}, json={'BaseRequest': {
            'DeviceID': self.device_id,
            'Sid': self.wx['wxsid'],
            'Skey': self.wx['skey'],
            'Uin': self.wx['wxuin']
        }})
        r.encoding = 'utf-8'
        log.debug('webwxinit response --> {}'.format(r.content.decode('utf-8', 'replace')))
        rjson = r.json()
        self.wx['User'] = rjson['User']
        self.wx['SyncKey'] = rjson['SyncKey']
        self._web_wx_status_notify()

    # noinspection PyTypeChecker
    def _web_wx_status_notify(self):
        log.info('start web wx status notify...')
        url = 'https://wx2.qq.com/cgi-bin/mmwebwx-bin/webwxstatusnotify'
        self.s.headers.update({'Content-Type': 'application/json;charset=UTF-8'})
        r = self.s.post(url, params={'lang': self.wx['lang'], 'pass_ticket': self.wx['pass_ticket']},
                        json={"BaseRequest": {"Uin": self.wx['wxuin'], "Sid": self.wx['wxsid'],
                                              "Skey": self.wx['skey'],
                                              "DeviceID": self.device_id}, "Code": 3,
                              "FromUserName": self.wx['User']['UserName'],
                              "ToUserName": self.wx['User']['UserName'],
                              "ClientMsgId": self.timestamp})
        log.debug('webwxstatusnotify response: --> {}'.format(r.content.decode('utf-8')))
        self._sync_check(self._web_wx_sync())

    # noinspection PyTypeChecker
    def _sync_check(self, c):
        c.send(None)
        log.info('sync check...')
        while 1:
            self.s.headers.pop('Content-Type', None)
            url = 'https://webpush.wx2.qq.com/cgi-bin/mmwebwx-bin/synccheck'
            r = self.s.get(url, params=dict(r=self.timestamp, skey=self.wx['skey'], sid=self.wx['wxsid'],
                                            uin=self.wx['wxuin'], deviceid=self.device_id,
                                            synckey='|'.join(map(lambda x: '{}_{}'.format(x['Key'], x['Val']),
                                                                 self.wx['SyncKey']['List'])), _=self.timestamp))
            r_txt = r.content.decode('utf-8')
            log.info('synccheck response --> {}'.format(r_txt))
            sync_check = ast.literal_eval(
                r_txt.replace('window.synccheck=', '').replace('retcode', '"retcode"').replace('selector',
                                                                                               '"selector"'))
            if sync_check['retcode'] != '0':
                c.close()
                log.warning('sync check failed --> {}'.format(r_txt))
                return
            if sync_check['selector'] == '0':
                pass
            else:
                c.send(1)

    def _web_wx_sync(self):
        while 1:
            d = yield
            if not d:
                break
            log.info('web wx sync new message...')
            self.s.headers.update({'Content-Type': 'application/json;charset=UTF-8'})
            url = 'https://wx2.qq.com/cgi-bin/mmwebwx-bin/webwxsync'
            r = self.s.post(url, params=dict(sid=self.wx['wxsid'], skey=self.wx['skey'], lang=self.wx['lang'],
                                             pass_ticket=self.wx['pass_ticket']
                                             ), json={"BaseRequest": {"Uin": self.wx['wxuin'], "Sid": self.wx['wxsid'],
                                                                      "Skey": self.wx['skey'],
                                                                      "DeviceID": self.device_id},
                                                      "SyncKey": self.wx['SyncKey'],
                                                      "rr": ~int(time.time())})
            r.encoding = 'utf-8'
            rjson = r.json()
            self.wx['SyncKey'] = rjson['SyncKey']
            log.debug('webwxsync response --> {}'.format(r.content.decode('utf-8')))

    def _webwxgetmsgimg(self, msg_id):
        url = 'https://wx2.qq.com/cgi-bin/mmwebwx-bin/webwxgetmsgimg'
        self.s.get(url, params=dict(MsgID=msg_id, skey=self.wx['skey'], type='big'))

    def _webwxsendemoticon(self, media_id, to_user_name):
        url = 'https://wx2.qq.com/cgi-bin/mmwebwx-bin/webwxsendemoticon'
        local_id = '{}1234'.format(self.timestamp)
        self.s.headers.update({'Content-Type': 'application/json;charset=UTF-8'})
        r = self.s.post(url, params=dict(fun='sys', lang='zh_CN', pass_ticket=self.wx['pass_ticket']),

                        json={"BaseRequest": {"Uin": self.wx['wxuin'], "Sid": self.wx['wxsid'],
                                              "Skey": self.wx['skey'],
                                              "DeviceID": self.device_id},
                              "Msg": {"Type": 47, "EmojiFlag": 2,
                                      "MediaId": media_id,
                                      "FromUserName": self.wx['User']['UserName'],
                                      "ToUserName": to_user_name, "LocalID": local_id,
                                      "ClientMsgId": local_id}, "Scene": 0}
                        )
        r.encoding = 'utf-8'
        return r.json()

if __name__ == '__main__':
    bot = WebWeChatBot()
    bot.login()
