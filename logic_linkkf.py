# -*- coding: utf-8 -*-
#########################################################
# python
import os
import sys
import traceback
import logging
import threading
import time
import re
import random
import urlparse
import json
# third-party
import requests
from lxml import html

# sjva 공용
from framework import db, scheduler, path_data
from framework.job import Job
from framework.util import Util
from framework.logger import get_logger

# 패키지
from .plugin import package_name, logger
from .model import ModelSetting, ModelLinkkf
from .logic_queue import LogicQueue

#########################################################


class LogicLinkkf(object):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    session = None
    referer = 'panogas.com'
    current_data = None

    @staticmethod
    def get_html(url):
        try:
            if LogicLinkkf.session is None:
                LogicLinkkf.session = requests.Session()
            LogicLinkkf.headers['referer'] = LogicLinkkf.referer
            LogicLinkkf.referer = url
            page = LogicLinkkf.session.get(url, headers=LogicLinkkf.headers)
            return page.content.decode('utf8')
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_video_url(episode_id):
        try:
            url = '%s/%s' % (ModelSetting.get('linkkf_url'), episode_id)
            logger.debug("acess site" + str(url))
            data = LogicLinkkf.get_html(url)
            logger.debug(data)
            tree = html.fromstring(data)
            url2s = [tag.attrib['value']for tag in tree.xpath('//*[@id="body"]/div/div/span/center/select/option')]
            logger.debug("\n" + str(url2s))
            
            url2s = filter(lambda url:
                    ('kfani' in url) |
                    ('linkkf' in url) | 
                    ('kftv' in url), url2s)
            #url2 = random.choice(url2s)
            url2 = url2s[0]

            if ('kfani' in url2):
                # kfani 계열 처리 => 방문해서 m3u8을 받아온다.
                LogicLinkkf.referer = url
                data = LogicLinkkf.get_html(url2)
                regex2 = r'"([^\"]*m3u8)"'
                video_url = re.findall(regex2, data)[0]

            if ('kftv' in url2):
                # kftv 계열 처리 => url의 id로 https://yt.kftv.live/getLinkStreamMd5/df6960891d226e24b117b850b44a2290 페이지 접속해서 json 받아오고, json에서 url을 추출해야함
                md5 = urlparse.urlparse(url2).query.split('=')[1]
                url3 = 'https://yt.kftv.live/getLinkStreamMd5/' + md5
                data3 = LogicLinkkf.get_html(url3)
                data3dict = json.loads(data3)
                # print(data3dict)
                video_url = data3dict[0]['file']
                
            if( 'linkkf' in url2):
                # linkkf 계열 처리 => URL 리스트를 받아오고, 하나 골라 방문해서 m3u8을 받아온다.
                LogicLinkkf.referer = url
                data = LogicLinkkf.get_html(url2)
                # print(data)
                regex = r'"(\/[^\"]*)"'
                url3s = re.findall(regex, data)
                url3 = random.choice(url3s)
                url3 = urlparse.urljoin(url2, url3)
                LogicLinkkf.referer = url2
                data = LogicLinkkf.get_html(url3)
                # print(data)
                regex2 = r'"([^\"]*m3u8)"'
                video_url = re.findall(regex2, data)[0]
            
            return video_url
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


    @staticmethod
    def get_title_info(code):
        try:
            if LogicLinkkf.current_data is not None and LogicLinkkf.current_data['code'] == code and LogicLinkkf.current_data['ret']:
                return LogicLinkkf.current_data
            url = '%s/%s' % (ModelSetting.get('linkkf_url'), code)
            data = LogicLinkkf.get_html(url)
            tree = html.fromstring(data)

            data = {}
            data['code'] = code
            data['ret'] = False
            tmp = tree.xpath('/html/body/div[2]/div/div/article/center/strong')[0].text_content().strip().encode('utf8')
            match = re.compile(r'(?P<season>\d+)기').search(tmp)
            if match:
                data['season'] = match.group('season')
            else:
                data['season'] = '1'
            data['title'] = tmp.replace(data['season']+u'기', '').strip()
            data['title'] = Util.change_text_for_use_filename(data['title']).replace('OVA', '').strip()
            try:
                data['poster_url'] = tree.xpath('//*[@id="body"]/div/div/div[1]/center/img')[0].attrib['data-src']
                data['detail'] = [{'info':tree.xpath('/html/body/div[2]/div/div/div[1]')[0].text_content().strip().encode('utf8')}]
            except:
                data['detail'] = [{'정보없음':''}]
                data['poster_url'] = None

            tmp = tree.xpath('//*[@id="relatedpost"]/ul/li')
            if tmp is not None:
                data['episode_count'] = len(tmp)
            else:
                data['episode_count'] = '0'

            data['episode'] = []
            tags = tree.xpath('//*[@id="relatedpost"]/ul/li/a')
            re1 = re.compile(r'\/(?P<code>\d+)')
            
            for t in tags:
                entity = {}
                entity['program_code'] = data['code']
                entity['program_title'] = Util.change_text_for_use_filename(data['title'])
                entity['code'] = re1.search(t.attrib['href']).group('code')
                data['episode'].append(entity)
                entity['image'] = data['poster_url']
                entity['title'] = t.text_content().strip().encode('utf8')
                entity['filename'] = LogicLinkkf.get_filename(data['title'], entity['title'])
            data['ret'] = True
            LogicLinkkf.current_data = data
            return data
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            data['log'] = str(e)
            return data
    
    @staticmethod
    def get_filename(maintitle, title):
        try:
            match = re.compile(r'(?P<title>.*?)\s?((?P<season>\d+)기)?\s?((?P<epi_no>\d+)화)').search(title)
            if match:
                if match.group('season') is not None:
                    season = int(match.group('season'))
                    if season < 10:
                        season = '0%s' % season
                    else:
                        season = '%s' % season
                else:
                    season = '01'

                epi_no = int(match.group('epi_no'))
                if epi_no < 10:
                    epi_no = '0%s' % epi_no
                else:
                    epi_no = '%s' % epi_no

                #title_part = match.group('title').strip()
                #ret = '%s.S%sE%s%s.720p-SA.mp4' % (maintitle, season, epi_no, date_str)
                ret = '%s S%sE%s.mp4' % (maintitle, season, epi_no)
            else:
                logger.debug('NOT MATCH')
                ret = '%s.720p-SA.mp4' % title
            
            return Util.change_text_for_use_filename(ret)
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def get_info_by_code(code):
        try:
            if LogicLinkkf.current_data is not None:
                for t in LogicLinkkf.current_data['episode']:
                    if t['code'] == code:
                        return t
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def scheduler_function():
        try:
            logger.debug('Linkkf scheduler_function start..')

            whitelist_program = ModelSetting.get('whitelist_program') 
            whitelist_programs = [x.strip().replace(' ', '') for x in whitelist_program.replace('\n', ',').split(',')]
            
            for code in whitelist_programs:
                logger.info('auto download start : %s', code)
                downloaded = db.session.query(ModelLinkkf) \
                            .filter(ModelLinkkf.completed.is_(True)) \
                            .filter_by(programcode=code) \
                            .with_for_update().all()
                dl_codes = [dl.episodecode for dl in downloaded]
                logger.info('downloaded codes :%s', dl_codes)
                data = LogicLinkkf.get_title_info(code)
                for episode in data['episode']:
                    e_code = episode['code']
                    if(e_code not in dl_codes):
                        logger.info('Logic Queue added :%s', e_code)
                        LogicQueue.add_queue(episode)
                        
            logger.debug('=======================================')
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
