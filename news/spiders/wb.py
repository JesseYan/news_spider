# -*- coding: utf-8 -*-


from __future__ import print_function
from __future__ import unicode_literals

import json
import time

import scrapy

from apps.client_db import get_item
from maps.channel import channel_name_map
from maps.platform import platform_name_map
from models.news import FetchTask
from news.items import FetchResultItem
from tools.date_time import time_local_to_utc
from tools.scrapy_tasks import pop_task
from tools.toutiao_m import get_as_cp, ParseJsTt, parse_toutiao_js_body
from tools.url import get_update_url


class ToutiaoMSpider(scrapy.Spider):
    """
    头条蜘蛛
    """
    name = 'wb'
    web_host_url = "https://m.toutiao.com"
    allowed_domains = ['toutiao.com', 'snssdk.com', web_host_url]
    DOWNLOAD_DELAY = 0.5
    FRESH_DELAY = 1*60

    custom_settings = dict(
        COOKIES_ENABLED=True,
        DEFAULT_REQUEST_HEADERS={
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.13; rv:57.0) Gecko/20100101 Firefox/57.0'
        },
        USER_AGENT='Mozilla/5.0 (Macintosh; Intel Mac OS X 10.13; rv:57.0) Gecko/20100101 Firefox/57.0',
        DOWNLOADER_MIDDLEWARES={
            'news.middlewares.de_duplication_request.DeDuplicationRequestMiddleware': 140,  # 去重请求
            # 'news.middlewares.anti_spider.AntiSpiderMiddleware': 160,  # 反爬处理
            'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
            'news.middlewares.useragent.UserAgentMiddleware': 500,
            # 'news.middlewares.httpproxy.HttpProxyMiddleware': 720,
        },
        ITEM_PIPELINES={
            'news.pipelines.de_duplication_store_mysql.DeDuplicationStoreMysqlPipeline': 400,  # 去重存储
            'news.pipelines.store_mysql.StoreMysqlPipeline': 450,
            'news.pipelines.de_duplication_request.DeDuplicationRequestPipeline': 500,  # 去重请求
        },
        DOWNLOAD_DELAY=DOWNLOAD_DELAY
    )

    # start_urls = ['http://toutiao.com/']
    # start_urls = ['https://www.toutiao.com/ch/news_finance/']

    def start_requests(self):
        """
        入口准备
        :return:
        """
        url_params = {
            'version_code': '6.4.2',
            'version_name': '',
            'device_platform': 'iphone',
            'tt_from': 'weixin',
            'utm_source': 'weixin',
            'utm_medium': 'toutiao_ios',
            'utm_campaign': 'client_share',
            'wxshare_count': '1',
        }
        url = 'http://open.snssdk.com/jssdk_signature/'
        url_params = {
            'appid': 'wxe8b89be1715734a0',
            'noncestr': 'Wm3WZYTPz0wzccnW',
            'timestamp': '%13d' % (time.time() * 1000),
            'callback': 'jsonp2',
        }
        url_jssdk_signature = get_update_url(url, url_params)
        yield scrapy.Request(url=url_jssdk_signature,
                             callback=self.jssdk_signature,
                             headers=self.custom_settings['DEFAULT_REQUEST_HEADERS'],
                             cookies=None)

    def get_profile(self, response):
        userid = response.xpath('//button[@itemid="topsharebtn"]/@data-userid').extract_first(default='')
        mediaid = response.xpath('//button[@itemid="topsharebtn"]/@data-mediaid').extract_first(default='')

        meta = dict(response.meta, userid=userid, mediaid=mediaid)

        url = 'http://open.snssdk.com/jssdk_signature/'
        url_params = {
            'appid': 'wxe8b89be1715734a0',
            'noncestr': 'Wm3WZYTPz0wzccnW',
            'timestamp': '%13d' % (time.time() * 1000),
            'callback': 'jsonp2',
        }
        url_jssdk_signature = get_update_url(url, url_params)
        yield scrapy.Request(url=url_jssdk_signature,
                             callback=self.jssdk_signature, meta=meta,
                             headers=self.custom_settings['DEFAULT_REQUEST_HEADERS'],
                             cookies=None)

    def jssdk_signature(self, response):
        AS, CP = get_as_cp()
        jsonp_index = 3

        url = 'https://m.toutiao.com/list/'
        # url_params = {
        #     'page_type': 1,
        #     'max_behot_time': '',
        #     'uid': response.meta['userid'],
        #     'media_id': response.meta['mediaid'],
        #     'output': 'json',
        #     'is_json': 1,
        #     'count': 20,
        #     'from': 'user_profile_app',
        #     'version': 2,
        #     'as': AS,
        #     'cp': CP,
        #     'callback': 'jsonp%d' % jsonp_index,
        # }
        url_params = {
            'tag': 'news_hot',
            'max_behot_time': '%10d' % time.time(),
            'format': 'json_raw',
            'output': 'json',
            'is_json': 1,
            'count': 20,
            'version': 2,
            'as': AS,
            'cp': CP,
            'callback': 'jsonp%d' % jsonp_index,
        }
        url_article_list = get_update_url(url, url_params)
        # url_article_list = "https://m.toutiao.com/list/?tag=__all__&ac=wap&count=20&format=json_raw&as=A1755BB952EA81E&cp=5B922AF8A19E2E1&max_behot_time=1536333324"

        print("===url_article_list:", url_article_list)

        meta = dict(response.meta, jsonp_index=jsonp_index)
        # print("===meta:", meta)

        # print("===headers:", response.headers)

        yield scrapy.Request(url=url_article_list, callback=self.parse_article_list, meta=meta)

    def parse_article_list(self, response):
        """
        文章列表
        :param response:
        :return:
        """
        body = response.body_as_unicode()
        # print("headers:===\n", response.request.headers)
        # print("body:====\n", body)

        jsonp_text = 'jsonp%d' % response.meta.get('jsonp_index', 0)
        result = json.loads(body.lstrip('%s(' % jsonp_text).rstrip(')'))

        # 详情
        data_list = result.get('data', [])
        print("\n====data_list len:", len(data_list))
        for data_item in data_list:
            detail_url = self.web_host_url + data_item.get('source_url') + 'info/'
            print("****detail_url:", detail_url)
            article_url = self.web_host_url + data_item.get('source_url')

            article_id = data_item['item_id']
            article_title = data_item['title']
            pub_time = data_item['behot_time']
            keywords = data_item['keywords'] if 'keywords' in data_item else ''

            meta = dict(response.meta,
                        detail_url=detail_url,
                        article_url=article_url,
                        item_id=article_id,
                        article_title=article_title,
                        article_pub_time=pub_time,
                        keywords=keywords,
                        )
            yield scrapy.Request(url=detail_url, callback=self.parse_article_detail, meta=meta)

        # 翻页
        has_more = result.get('has_more')
        if has_more:
            max_behot_time = ''
            if 'next' in result and 'max_behot_time' in result['next']:
                max_behot_time = result['next']['max_behot_time']
            AS, CP = get_as_cp()
            jsonp_index = response.meta.get('jsonp_index', 0) + 1

            url_params_next = {
                'max_behot_time': max_behot_time or '%10d' % time.time(),
                'as': AS,
                'cp': CP,
                'callback': 'jsonp%d' % jsonp_index,
            }
            print("max_behot_time:", url_params_next['max_behot_time'])

            url_article_list_next = get_update_url(response.url, url_params_next)

            meta = dict(response.meta, jsonp_index=jsonp_index)
            time.sleep(self.FRESH_DELAY)
            yield scrapy.Request(url=url_article_list_next, callback=self.parse_article_list, meta=meta)

    def parse_article_detail(self, response):
        """
        文章详情
        :param response:
        :return:
        """
        body = response.body_as_unicode()
        result = json.loads(body)['data']

        # print("==article body:", toutiao_body)
        # fixme add 评论数，阅读数；
        print('\n====result:', result)
        impression_count = result['impression_count'] if 'impression_count' in result else 0
        comment_count = result['comment_count'] if 'comment_count' in result else 0

        fetch_result_item = FetchResultItem()
        fetch_result_item['task_id'] = 0
        fetch_result_item['platform_id'] = 0
        fetch_result_item['platform_name'] = platform_name_map.get(3, '')
        fetch_result_item['channel_id'] = 0
        fetch_result_item['channel_name'] = '0'
        fetch_result_item['article_id'] = response.meta['item_id']
        fetch_result_item['article_title'] = response.meta['article_title']
        fetch_result_item['article_pub_time'] = time_local_to_utc(response.meta['article_pub_time']).strftime('%Y-%m-%d %H:%M:%S')
        fetch_result_item['article_url'] = response.meta['article_url']
        fetch_result_item['article_tags'] = response.meta.get('keywords')
        fetch_result_item['article_abstract'] = ''
        fetch_result_item['article_content'] = result['content']
        fetch_result_item['impression_count'] = impression_count
        fetch_result_item['comment_count'] = comment_count

        print("===crawl url:", fetch_result_item['article_url'])

        yield fetch_result_item
