# coding=utf-8
import json
from _md5 import md5
from multiprocessing.pool import Pool
import re
import os
import requests
from urllib.parse import urlencode
from bs4 import BeautifulSoup

START_OFFSET = 0
END_OFFSET = 10

# https://blog.csdn.net/qq_36124802/article/details/80446671
# 链接mongodb数据库,多进程这里可能会报警告
# client = pymongo.MongoClient(MONGO_URL,connect=False)
# 定义一个数据库
#   db = client[MONGO_DB]

KEYWORD = '脉动'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.146 Safari/537.36'
}


def get_page_list(offset, keyword):
    '''
       获取主页面所有帖子的链接
    '''
    # 请求ajax的一些参数，通过浏览器F12看到的
    params = {
        'offset': offset,
        'format': 'json',
        'keyword': keyword,
        'autoload': 'true',
        'count': '20',
        'cur_tab': 1,
        'from': 'search_tab'
    }
    # from urllib.parse import urlencode  # 用下面这种要import这个
    # url解析自带的，就是把那个参数弄成一个链接,教程用的是下面这种方式把参数和url拼接
    url = 'https://www.toutiao.com/search_content/?' + urlencode(params)

    # url = 'https://www.toutiao.com/search_content'
    try:
        # 我是把参数传入到get请求里面，如果用上面那种，这里的params形参就要删掉
        # response = requests.get(url,headers = HEADERS,params=params)
        response = requests.get(url)
        # 因为要返回的是一个文本，所以用response.text，若要返回二进制数据，用response.content
        return response.text
    except:
        # 可能会url请求出错，避免停止，捕获一下异常
        return None


def parse_page_list(html):
    '''
    解析主页，取得帖子的链接
    '''
    # 把得到的ajax弄成一个json，方便处理，另外，注意是loads不是load
    data = json.loads(html)
    # 下面的内容是分析浏览器F12的network中的各种数据得到的
    if data and 'data' in data.keys():
        # 数据是层层字典嵌套的，一步步取出来
        for item in data.get('data'):
            # 这个yield如果不懂可以理解为return的高级版本
            yield item.get('article_url')


def get_page_detail(url):
    '''
    根据主页的那些链接，访问帖子
    '''
    try:
        # print('find')
        response = requests.get(url, headers=HEADERS)
        # 不加头直接get,有可能遇到反爬虫
        # 帖子请求成功才返回
        # print('result= ' , response)
        if response.status_code == 200:
            return response.text
        return None
    except:
        return None


def parse_page_detail(html):
    # 爬取帖子里面的所以照片链接和帖子名称
    try:
        # 一开始用的正则，有点小错误，直接拿汤器祭神
        # print('~~')
        soup = BeautifulSoup(html, 'lxml')
        # print('44')
        # 用选择，直接找到项目为title的内容
        title = soup.select('title')[0].get_text()
        # print(title)
        # 这是图片的正则模式
        # pattern = re.compile('"(http://p3.pstatp.com/origin/213a0000d62a02db7e89)"', re.S)
        # pattern = re.compile('"(http:.*?)"', re.S)
        pattern = re.compile('"(http:.*?)"', re.S)
        # 把所有包含http的内容均储存下来
        # pattern = re.compile('articleInfo:.*?title: \'(.*?)\'.*?content.*?\'(.*?)\'', re.S)
        # pattern = re.compile('gallery:=(.*?);', re.S)#先匹配到http
        # result = re.search(pattern,html) #对字符串进行解析
        # print(result)
        # if result:
        #    data = json.loads(result)
        # pattern = re.compile('articleInfo:.*?title: \'(.*?)\'.*?content.*?\'(.*?)\'', re.S)
        # re模块提供对正则表达式的支持,获取一个匹配结果
        # 找到所有的图片链接
        images = re.findall(pattern, html)
        # 把找到的信息作为数组存储在里面
    except:
        return None
        # 以特定格式返回，title是str，images是list
    return {
        'title': title,
        'images': images
    }


def save_to_mongo(result):
    '''
    存储
    {
        'title':title,
        'images':images
    }
    '''
    # 把结果插入到表MONGO_TABLE中，成功返回True，失败False
    if db[MONGO_TABLE].insert(result):
        print('存到mongodb成功: ', result['title'])
        return True
    return False


def download_save_image(url):
    '''
    下载图片，并保存到本地
    '''
    try:
        # 封装请求
        # print('to find' ,url)
        response = requests.get(url, headers=HEADERS)
        # 如果是图片就返回content好，如果是网页就text
        content = response.content
        # print(content)
        # 图片的存路径，因为图片可能会重复，所以加一个md5的命名规则，避免重复下载
        file_path = '{0}/images/{1}.{2}'.format(os.getcwd(), md5(content).hexdigest(), 'jpg')
        # os.getcwd()为目前的相对路径
        #
        # 我是把图片都放在images文件夹下，如果还要分得更细，可以再创建一个"./images/图片集名字"这样的文件夹
        dir = '{0}/images'.format(os.getcwd())
        # 如果没有images文件夹，就新建一个
        if not os.path.exists(dir):
            os.mkdir(dir)
        # 这个就是创建图片（因为用了md5，所以不允许有重复的图片）
        if not os.path.exists(file_path):
            with open(file_path, 'wb') as f:
                f.write(content)
            print('图片保存成功：' + url)
    except:
        return None


def main(offset):
    # 获取主页html
    html = get_page_list(offset, KEYWORD)
    # 解析上面的html得到链接
    url_list = parse_page_list(html)
    for url in url_list:
        # 进入详情页
        # print(url)
        html = get_page_detail(url)
        if html:
            # continue
            # print('before',html)
            # 得到详情页的图片链接
            result = parse_page_detail(html)
            # print(result)
            # 如果图片链接结果不为空
            if result and result['images']:
                #     # 先存相关信息到mongo
                #     save_to_mongo(result)
                #     # 再下载一份到本地
                for url in result['images']:  # 如果里面存在image
                    url = url.replace('\\', '')  # 这里多出来的\\可以替换掉
                    len1 = len(url)
                    if url[7] != 'p' or len1 <= 21:
                        continue
                    # print(url)#这里得到的url为正则得到的url
                    download_save_image(url)


if __name__ == '__main__':
    # 三行加起来是并行进行
    # main(1)
    # l = [i*20 for i in range(START_OFFSET,END_OFFSET)]
    pool = Pool()
    pool.map(main, 0)
    # l = [i*20 for i in range(START_OFFSET,END_OFFSET)]
    # pool = Pool()
