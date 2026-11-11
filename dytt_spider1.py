import requests
from lxml import etree
import random
import time
import urllib3
import pymysql
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 禁用SSL证书验证警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------- 数据库连接模块 ----------------------------
def get_conn():
    try:
        conn = pymysql.connect(
            host='localhost',
            user='root',
            passwd='your_password_here',
            database='dytt',
            port=3306,
            charset='utf8mb4'
        )
        cursor = conn.cursor()
        print("数据库连接成功")
        return conn, cursor
    except pymysql.Error as e:
        print(f"数据库连接失败: {e}")
        raise


# ---------------------------- 网络请求配置模块 ----------------------------
class RequestModel(object):
    UserAgent_List = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    @classmethod
    def get_headers(cls):
        return {
            'User-Agent': random.choice(cls.UserAgent_List),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Referer': 'https://www.dydytt.net/'
        }

    @classmethod
    def get_session(cls):
        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,  #1, 2, 4
            status_forcelist=[500, 502, 503, 504]
        )

        session.mount('https://', HTTPAdapter(max_retries=retries))
        session.mount('http://', HTTPAdapter(max_retries=retries))
        return session


# ---------------------------- 主要爬虫类 ----------------------------
class DyttSpider:
    def __init__(self, max_pages=2):
        self.base_url = 'https://www.dydytt.net'  # 网站根地址
        self.start_url = 'https://www.dydytt.net/html/gndy/dyzz/index.html'  # 起始页
        self.max_pages = max_pages  # 最大爬取页数限制
        self.session = RequestModel.get_session()  # 获取配置好的会话对象
        self.movies_data = []

    def get_page_count(self):
        try:
            # 发送起始页请求
            response = self.session.get(
                self.start_url,
                headers=RequestModel.get_headers(),
                verify=True
            )
            response.encoding = 'gb18030'  # 指定页面编码
            # 使用XPath解析页面获取最大页码
            html = etree.HTML(response.text)
            last_page = html.xpath('//select[@name="sldd"]/option[last()]/@value')[0]
            # 解析页码并限制最大页数
            page_num = int(last_page.split('_')[-1].split('.')[0])
            return min(page_num, self.max_pages)
        except Exception as e:
            print(f'获取总页数失败: {e}')
            return 1  # 失败时默认只爬取1页

    def _safe_request(self, url):
        try:
            response = self.session.get(
                url,
                headers=RequestModel.get_headers(),
                timeout=15,
                verify=True  # 启用SSL验证
            )
            response.encoding = 'gb18030'
            return response
        except Exception as e:
            print(f'请求失败[{url}]: {e}')
            return None

    def get_movie_list(self, page_url):
        response = self._safe_request(page_url)
        if not response:
            return []

        # 使用XPath提取电影链接
        html = etree.HTML(response.text)
        links = html.xpath('//div[@class="co_content8"]//td[2]/b/a/@href')

        # 处理相对路径链接
        return [
            self.base_url + link if not link.startswith('http') else link
            for link in links
        ]

    def parse_movie_detail(self, detail_url):
        response = self._safe_request(detail_url)
        if not response:
            return None

        html = etree.HTML(response.text)
        movie_info = {'url': detail_url}

        try:
            # 定位主要信息区域
            zoom_div = html.xpath('//div[@id="Zoom"]')[0]

            # 字段映射表（中文标识 -> 英文字段名）
            info_mapping = {
                'trans_name': '◎译　　名',
                'name': '◎片　　名',
                'year': '◎年　　代',
                'country': '◎产　　地',
                'genre': '◎类　　别',
                'language': '◎语　　言',
                'subtitle': '◎字　　幕',
                'release_date': '◎上映日期',
                'imdb_score': '◎IMDb评分',
                'douban_score': '◎豆瓣评分',
                'duration': '◎片　　长',
                'director': '◎导　　演',
                'actors': '◎主　　演'
            }

            # 遍历所有文本节点进行信息提取
            for line in zoom_div.xpath('.//text()'):
                line = line.strip()
                for key, prefix in info_mapping.items():
                    if line.startswith(prefix):
                        # 提取并清洗字段值
                        movie_info[key] = line.replace(prefix, '').strip()
                        break  # 找到匹配后跳出内层循环

            # 处理封面图片
            cover_img = html.xpath('//div[@id="Zoom"]//img/@src')
            movie_info['cover'] = cover_img[0] if cover_img else ''

            # ----------------- 数据清洗阶段 -----------------
            # 处理上映日期格式（提取第一个日期）
            if movie_info.get('release_date'):
                date_str = movie_info['release_date']
                first_date = date_str.split('/',1)[0].split('(',1)[0].strip()
                movie_info['release_date'] = first_date

            # 处理评分格式（提取分数部分）
            for score_field in ['douban_score', 'imdb_score']:
                if movie_info.get(score_field):
                    score = movie_info[score_field].split('/')[0].strip()
                    movie_info[score_field] = score

            # 处理片长时间（提取数字部分）
            if movie_info.get('duration'):
                duration = movie_info['duration'].split('分')[0].strip()
                movie_info['duration'] = duration



            return movie_info
        except Exception as e:
            print(f'解析失败[{detail_url}] {e}')
            return None

    def run(self):
        # 获取实际总页数
        total_pages = self.get_page_count()
        print(f'共发现{total_pages}页数据')

        # 遍历所有列表页
        for page in range(1, total_pages + 1):
            # 生成列表页地址（第一页地址特殊）
            page_url = f'{self.base_url}/html/gndy/dyzz/list_23_{page}.html' \
                if page > 1 else self.start_url
            print(f'\n正在获取第{page}页: {page_url}')

            # 获取当前页电影链接
            movie_links = self.get_movie_list(page_url)
            print(f'本页找到了{len(movie_links)}部电影')

            # 遍历处理每部电影
            for idx, link in enumerate(movie_links, 1):
                print(f'正在处理第{idx}部电影')
                movie_data = self.parse_movie_detail(link)
                if movie_data:
                    print('成功获取:', movie_data.get('name', '名称不存在'))
                    self.movies_data.append(movie_data)
                else:
                    print('获取失败')
                time.sleep(random.uniform(1, 3))

        self._save_to_db()



    def _save_to_db(self):
        if not self.movies_data:
            print("没有需要保存的数据")
            return

        # 获取数据库连接
        conn, cursor = get_conn()
        if not conn or not cursor:
            print("数据库连接失败")
            return

        success_count = 0
        error_count = 0

        # SQL插入语句（字段顺序需严格匹配）
        sql = """
            INSERT INTO movie (
                name, trans_name, year, country, genre, language, subtitle,
                release_date, imdb_score, douban_score, duration,
                director, actors, cover_url, detail_url
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """

        # 遍历所有电影数据进行插入
        for movie in self.movies_data:
            try:
                # ================= 数据预处理 =================
                # 处理必填字段（NOT NULL约束）
                name = movie.get('name', '未知电影').strip() or '未知电影'
                detail_url = movie.get('url', '').strip() or '无URL'

                # 处理年份（转换为整数）
                year_str = movie.get('year', '')
                year = int(year_str) if year_str.isdigit() else None

                # 处理IMDb评分（字符串转浮点数）
                imdb_score = None
                if movie.get('imdb_score'):
                    try:
                        imdb_score = float(movie['imdb_score'].split('/')[0].strip())
                    except (ValueError, AttributeError):
                        pass

                # 处理豆瓣评分（同上）
                douban_score = None
                if movie.get('douban_score'):
                    try:
                        douban_score = float(movie['douban_score'].split('/')[0].strip())
                    except (ValueError, AttributeError):
                        pass

                # 处理片长时间（提取数字部分）
                duration = None
                if movie.get('duration'):
                    try:
                        duration_str = movie['duration'].replace('分钟', '').strip()
                        duration = int(duration_str)
                    except (ValueError, AttributeError):
                        pass

                # 处理国家（取第一个国家）
                country = movie.get('country', '')
                if '/' in country:
                    country = country.split('/')[0].strip()

                # 构建数据元组（顺序需严格匹配SQL语句）
                data = (
                    name,  # 电影名称
                    movie.get('trans_name', '').strip(),  # 译名
                    year,  # 上映年份
                    country,  # 国家地区
                    movie.get('genre', '').replace('/', ','),  # 类型（替换斜杠为逗号）
                    movie.get('language', '').strip(),  # 语言
                    movie.get('subtitle', '').strip(),  # 字幕
                    movie.get('release_date', '').strip(),  # 上映日期
                    imdb_score,  # IMDb评分（浮点）
                    douban_score,  # 豆瓣评分（浮点）
                    duration,  # 片长（整数分钟）
                    movie.get('director', '').strip(),  # 导演
                    movie.get('actors', '').strip(),  # 主演
                    movie.get('cover', '').strip(),  # 封面URL
                    detail_url  # 详情页URL
                )

                # 执行单条插入
                cursor.execute(sql, data)
                success_count += 1

            except pymysql.Error as e:
                # 处理数据库错误（如唯一键冲突）
                error_count += 1
                print(f"数据库错误（第{success_count + error_count}条）: {e}")
                conn.rollback()  # 回滚当前事务
            except Exception as e:
                # 处理数据格式错误
                error_count += 1
                print(f"数据处理错误（第{success_count + error_count}条）: {e}")
                print(f"问题数据: {movie}")
                continue

        # 最终提交事务
        try:
            conn.commit()
            print(f"\n保存成功：{success_count}条，失败：{error_count}条")
        except Exception as e:
            print(f"最终提交失败: {e}")
        finally:
            # 关闭数据库连接
            cursor.close()
            conn.close()

if __name__ == '__main__':
    spider = DyttSpider(max_pages=100)
    spider.run()

