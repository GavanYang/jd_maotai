#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import json
import os
import pickle
import random
import sys
import time
from datetime import datetime
from lxml import etree
import requests

from config import global_config
from jdlogger import logger
from timer import Timer
from util import parse_json, get_session, send_wechat, save_image, open_image, check_login


class JdMaskSpider(object):
    def __init__(self):
        # 初始化信息
        self.session = get_session()
        self.sku_id = global_config.getRaw('config', 'sku_id')
        self.seckill_init_info = dict()
        self.seckill_url = dict()
        self.seckill_order_data = dict()
        self.timers = Timer()
        self.default_user_agent = global_config.getRaw(
            'config', 'DEFAULT_USER_AGENT')
        self.is_login = False
        self.time_diff = 0.1
        self.nick_name = ''
        print("京东时间:%s\n本地时间:%s" %
              (datetime.fromtimestamp(self.getJdTime()), datetime.now()))

    def _load_cookies(self):
        cookies_file = ''
        for name in os.listdir('./cookies'):
            if name.endswith('.cookies'):
                cookies_file = './cookies/{0}'.format(name)
                break
        with open(cookies_file, 'rb') as f:
            local_cookies = pickle.load(f)
        self.session.cookies.update(local_cookies)
        self.is_login = self._validate_cookies()

    def _save_cookies(self):
        cookies_file = './cookies/{0}.cookies'.format(self.nick_name)
        directory = os.path.dirname(cookies_file)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(cookies_file, 'wb') as f:
            pickle.dump(self.session.cookies, f)

    def _validate_cookies(self):
        """
        验证cookies是否有效（是否登陆）
        通过访问用户订单列表页进行判断：若未登录，将会重定向到登陆页面。
        :return: cookies是否有效
        True / False
        """
        url = 'https://order.jd.com/center/list.action'
        payload = {
            'rid': str(int(time.time() * 1000)),
        }
        try:
            resp = self.session.get(
                url=url, params=payload, allow_redirects=False)
            if resp.ok:
                return True
        except Exception as e:
            logger.error(e)

        self.session = requests.session()
        return False

    def get_sku_title(self):
        """获取商品名称"""
        url = 'https://item.jd.com/{}.html'.format(
            global_config.getRaw('config', 'sku_id'))
        resp = self.session.get(url).content
        x_data = etree.HTML(resp)
        sku_title = x_data.xpath('/html/head/title/text()')
        return sku_title[0]

    def getJdTime(self):
        url = 'https://a.jd.com//ajax/queryServerData.html'
        resp = self.session.get(url).text
        js = json.loads(resp)
        return float(js.get('serverTime') / 1000)

    def login(self):
        for flag in range(3):
            try:
                targetURL = 'https://order.jd.com/center/list.action'
                payload = {
                    'rid': str(int(time.time() * 1000)),
                }
                resp = self.session.get(
                    url=targetURL, params=payload, allow_redirects=False)
                if resp.ok:
                    logger.info('校验是否登录[成功]')
                    logger.info('用户:{}'.format(self.get_user_info()))
                    return True
                else:
                    logger.info('校验是否登录[失败]')
                    logger.info('请重新输入cookie')
                    time.sleep(1)
                    continue
            except Exception as e:
                logger.info('第【%s】次失败请重新获取cookie', flag)
                time.sleep(1)
        sys.exit(1)

    def login_by_QRcode(self):
        """二维码登陆
        :return:
        """
        if self.is_login:
            logger.info('登录成功')
            return

        self._get_login_page()

        # download QR code
        if not self._get_QRcode():
            logger.info('二维码下载失败')
            return

        # get QR code ticket
        ticket = None
        retry_times = 85
        for _ in range(retry_times):
            ticket = self._get_QRcode_ticket()
            if ticket:
                break
            time.sleep(2)
        else:
            logger.info('二维码过期，请重新获取扫描')
            return

        # validate QR code ticket
        if not self._validate_QRcode_ticket(ticket):
            logger.info('二维码信息校验失败')
            return
        logger.info('二维码登录成功')
        self.is_login = True
        self.nick_name = self.get_user_info()
        # self._save_cookies()

    def _get_login_page(self):
        url = "https://passport.jd.com/new/login.aspx"
        headers = {
            'User-Agent': self.default_user_agent,
        }
        page = self.session.get(url=url, headers=headers)
        return page

    def _get_QRcode(self):
        url = 'https://qr.m.jd.com/show'
        payload = {
            'appid': 133,
            'size': 147,
            't': str(int(time.time() * 1000)),
        }
        headers = {
            'User-Agent': self.default_user_agent,
            'Referer': 'https://passport.jd.com/new/login.aspx',
        }
        resp = self.session.get(url=url, headers=headers, params=payload)

        if not resp.ok:
            logger.info('获取二维码失败')
            return False

        QRCode_file = 'QRcode.png'
        save_image(resp, QRCode_file)
        logger.info('二维码获取成功，请打开京东APP扫描')
        open_image(QRCode_file)
        return True

    def _get_QRcode_ticket(self):
        url = 'https://qr.m.jd.com/check'
        payload = {
            'appid': '133',
            'callback': 'jQuery{}'.format(random.randint(1000000, 9999999)),
            'token': self.session.cookies.get('wlfstk_smdl'),
            '_': str(int(time.time() * 1000)),
        }
        headers = {
            'User-Agent': self.default_user_agent,
            'Referer': 'https://passport.jd.com/new/login.aspx',
        }
        resp = self.session.get(url=url, headers=headers, params=payload)

        if not resp.ok:
            logger.error('获取二维码扫描结果异常')
            return False

        resp_json = parse_json(resp.text)
        if resp_json['code'] != 200:
            logger.info('Code: %s, Message: %s',
                        resp_json['code'], resp_json['msg'])
            return None
        else:
            logger.info('已完成手机客户端确认')
            return resp_json['ticket']

    def _validate_QRcode_ticket(self, ticket):
        url = 'https://passport.jd.com/uc/qrCodeTicketValidation'
        headers = {
            'User-Agent': self.default_user_agent,
            'Referer': 'https://passport.jd.com/uc/login?ltype=logout',
        }
        resp = self.session.get(url=url, headers=headers, params={'t': ticket})

        if not resp.ok:
            return False
        resp_json = parse_json(resp.text)
        if resp_json['returnCode'] == 0:
            return True
        else:
            logger.info(resp_json)
            return False

    @check_login
    def get_user_info(self):
        """获取用户信息
        :return: 用户名
        """
        url = 'https://passport.jd.com/user/petName/getUserInfoForMiniJd.action'
        payload = {
            'callback': 'jQuery{}'.format(random.randint(1000000, 9999999)),
            '_': str(int(time.time() * 1000)),
        }
        headers = {
            'User-Agent': self.default_user_agent,
            'Referer': 'https://order.jd.com/center/list.action',
        }
        for _ in range(3):
            try:
                resp = self.session.get(url=url, params=payload, headers=headers)
                resp_json = parse_json(resp.text)
                if resp_json is None:
                    continue
                # many user info are included in response, now return nick name in it
                # jQuery2381773({"imgUrl":"//storage.360buyimg.com/i.imageUpload/xxx.jpg","lastLoginTime":"","nickName":"xxx","plusStatus":"0","realName":"xxx","userLevel":x,"userScoreVO":{"accountScore":xx,"activityScore":xx,"consumptionScore":xxxxx,"default":false,"financeScore":xxx,"pin":"xxx","riskScore":x,"totalScore":xxxxx}})
                return resp_json.get('nickName') or 'jd'
            except Exception:
                return 'jd'
        
    def make_reserve(self):
        """商品预约"""
        logger.info('用户:{}'.format(self.get_user_info()))
        logger.info('商品名称:{}'.format(self.get_sku_title()))
        url = 'https://yushou.jd.com/youshouinfo.action?'
        payload = {
            'callback': 'fetchJSON',
            'sku': self.sku_id,
            '_': str(int(time.time() * 1000)),
        }
        headers = {
            'User-Agent': self.default_user_agent,
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        resp = self.session.get(url=url, params=payload, headers=headers)
        resp_json = parse_json(resp.text)
        reserve_url = resp_json.get('url')
        self.timers.start()
        while True:
            try:
                self.session.get(url='https:' + reserve_url)
                logger.info('预约成功，已获得抢购资格 / 您已成功预约过了，无需重复预约')
                if global_config.getRaw('messenger', 'enable') == 'true':
                    success_message = "预约成功，已获得抢购资格 / 您已成功预约过了，无需重复预约"
                    send_wechat(success_message)
                break
            except Exception as e:
                logger.error('预约失败正在重试...')

    def get_seckill_url(self):
        """获取商品的抢购链接
        点击"抢购"按钮后，会有两次302跳转，最后到达订单结算页面
        这里返回第一次跳转后的页面url，作为商品的抢购链接
        :return: 商品的抢购链接
        """
        while True:
            url = 'https://itemko.jd.com/itemShowBtn'
            payload = {
                'callback': 'jQuery{}'.format(random.randint(1000000, 9999999)),
                'skuId': self.sku_id,
                'from': 'pc',
                '_': str(int(time.time() * 1000)),
            }
            headers = {
                'User-Agent': self.default_user_agent,
                'Host': 'itemko.jd.com',
                'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
            }
            resp = self.session.get(url=url, headers=headers, params=payload)
            if not resp.ok:
                continue
            if resp.text.find("{") != -1:
                resp_json = parse_json(resp.text)
            else:
                logger.info('获取抢购链接：{0}'.format(resp.text))
                continue
            if resp_json.get('url'):
                # https://divide.jd.com/user_routing?skuId=8654289&sn=c3f4ececd8461f0e4d7267e96a91e0e0&from=pc
                router_url = 'https:' + resp_json.get('url')
                # https://marathon.jd.com/captcha.html?skuId=8654289&sn=c3f4ececd8461f0e4d7267e96a91e0e0&from=pc
                seckill_url = router_url.replace('divide', 'marathon').replace(
                    'user_routing', 'captcha.html')
                logger.info("抢购链接获取成功: %s", seckill_url)
                return seckill_url
            else:
                logger.info("抢购链接获取失败，%s不是抢购商品或抢购页面暂未刷新，0.1秒后重试")
                time.sleep(0.1)

    def request_seckill_url(self):
        """访问商品的抢购链接（用于设置cookie等"""
        logger.info('用户:{}'.format(self.get_user_info()))
        logger.info('商品名称:{}'.format(self.get_sku_title()))
        self.timers.start()
        self.seckill_url[self.sku_id] = self.get_seckill_url()
        logger.info('访问商品的抢购连接...')
        headers = {
            'User-Agent': self.default_user_agent,
            'Host': 'marathon.jd.com',
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        self.session.get(
            url=self.seckill_url.get(
                self.sku_id),
            headers=headers,
            allow_redirects=False)

    def request_seckill_checkout_page(self):
        """访问抢购订单结算页面"""
        logger.info('访问抢购订单结算页面...')
        url = 'https://marathon.jd.com/seckill/seckill.action'
        payload = {
            'skuId': self.sku_id,
            'num': 1,
            'rid': int(time.time())
        }
        headers = {
            'User-Agent': self.default_user_agent,
            'Host': 'marathon.jd.com',
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        self.session.get(url=url, params=payload,
                         headers=headers, allow_redirects=False)

    def _get_seckill_init_info(self,times):
        """获取秒杀初始化信息（包括：地址，发票，token）
        :return: 初始化信息组成的dict
        """
        for i in range(3):
            logger.info('获取秒杀初始化信息:{}次...'.format(i))
            url = 'https://marathon.jd.com/seckillnew/orderService/pc/init.action'
            data = {
                'sku': self.sku_id,
                'num': 1,
                'isModifyAddress': 'false',
            }
            headers = {
                'User-Agent': self.default_user_agent,
                'Host': 'marathon.jd.com',
            }
            resp = self.session.post(url=url, data=data, headers=headers)
            if not resp.ok:
                continue
            if resp.text == "null":
                continue
            if resp.text.find("{") != -1:
                break
            else:
                logger.info('获取秒杀初始化信息 respText:' + resp.text)
        return parse_json(resp.text)

    def _get_seckill_order_data(self):
        """生成提交抢购订单所需的请求体参数
        :return: 请求体参数组成的dict
        """
        logger.info('生成提交抢购订单所需参数...')
        # 获取用户秒杀初始化信息
        try:
            self.seckill_init_info[self.sku_id] = self._get_seckill_init_info()
            init_info = self.seckill_init_info.get(self.sku_id)
            if init_info == None:
                return None
            default_address = init_info['addressList'][0]  # 默认地址dict
            invoice_info = init_info.get('invoiceInfo', {})  # 默认发票信息dict, 有可能不返回
            token = init_info['token']
            data = {
                'skuId': self.sku_id,
                'num': 1,
                'addressId': default_address['id'],
                'yuShou': 'true',
                'isModifyAddress': 'false',
                'name': default_address['name'],
                'provinceId': default_address['provinceId'],
                'cityId': default_address['cityId'],
                'countyId': default_address['countyId'],
                'townId': default_address['townId'],
                'addressDetail': default_address['addressDetail'],
                'mobile': default_address['mobile'],
                'mobileKey': default_address['mobileKey'],
                'email': default_address.get('email', ''),
                'postCode': '',
                'invoiceTitle': invoice_info.get('invoiceTitle', -1),
                'invoiceCompanyName': '',
                'invoiceContent': invoice_info.get('invoiceContentType', 1),
                'invoiceTaxpayerNO': '',
                'invoiceEmail': '',
                'invoicePhone': invoice_info.get('invoicePhone', ''),
                'invoicePhoneKey': invoice_info.get('invoicePhoneKey', ''),
                'invoice': 'true' if invoice_info else 'false',
                'password': '',
                'codTimeType': 3,
                'paymentType': 4,
                'areaCode': '',
                'overseas': 0,
                'phone': '',
                'eid': global_config.getRaw('config', 'eid'),
                'fp': global_config.getRaw('config', 'fp'),
                'token': token,
                'pru': ''
            }
            return data
        except Exception as e:
            logger.error('获取用户秒杀初始化信息失败{0},正在重试...'.format(e))
            return None
       
    def submit_seckill_order(self):
        """提交抢购（秒杀）订单
        :return: 抢购结果 True/False
        """
        url = 'https://marathon.jd.com/seckillnew/orderService/pc/submitOrder.action'
        payload = {
            'skuId': self.sku_id,
        }
        order_data=self._get_seckill_order_data()
        if order_data == None:
            return False
        self.seckill_order_data[self.sku_id] = order_data
        for skiltimes in range(3):
            try:
                logger.info('提交抢购订单:{}次...'.format(skiltimes))
                headers = {
                    'User-Agent': self.default_user_agent,
                    'Host': 'marathon.jd.com',
                    'Referer': 'https://marathon.jd.com/seckill/seckill.action?skuId={0}&num={1}&rid={2}'.format(
                        self.sku_id, 1, int(time.time())),
                }
                resp = self.session.post(
                    url=url,
                    params=payload,
                    data=self.seckill_order_data.get(self.sku_id),
                    headers=headers)
                if not resp.ok:
                    continue
                if resp.text=="null":
                    continue
                if resp.text.find("{") == -1:
                    logger.info('提交抢购订单respText:' + resp.text)
                    continue
                
                resp_json = parse_json(resp.text)
                # 返回信息
                # 抢购失败：
                # {'errorMessage': '很遗憾没有抢到，再接再厉哦。', 'orderId': 0, 'resultCode': 60074, 'skuId': 0, 'success': False}
                # {'errorMessage': '抱歉，您提交过快，请稍后再提交订单！', 'orderId': 0, 'resultCode': 60017, 'skuId': 0, 'success': False}
                # {'errorMessage': '系统正在开小差，请重试~~', 'orderId': 0, 'resultCode': 90013, 'skuId': 0, 'success': False}
                # 抢购成功：
                # {"appUrl":"xxxxx","orderId":820227xxxxx,"pcUrl":"xxxxx","resultCode":0,"skuId":0,"success":true,"totalMoney":"xxxxx"}
                if resp_json.get('success'):
                    order_id = resp_json.get('orderId')
                    total_money = resp_json.get('totalMoney')
                    pay_url = 'https:' + resp_json.get('pcUrl')
                    logger.info('抢购成功，订单号:{}, 总价:{}, 电脑端付款链接:{}'.format(
                        order_id, total_money, pay_url))
                    if global_config.getRaw('messenger', 'enable') == 'true':
                        success_message = "抢购成功，订单号:{}, 总价:{}, 电脑端付款链接:{}".format(
                            order_id, total_money, pay_url)
                        send_wechat(success_message)
                    return True
                else:
                    logger.info('抢购失败，返回信息:{}'.format(resp_json))
                    if global_config.getRaw('messenger', 'enable') == 'true':
                        error_message = '抢购失败，返回信息:{}'.format(resp_json)
                        send_wechat(error_message)
                    continue
            except Exception as e:
                logger.error('提交抢购订单失败:{},正在重试...'.format(e))
