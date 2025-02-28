from flask import Flask, request
from urllib.parse import urlparse, parse_qs
import xml.etree.ElementTree as ET
import json
import sqlite3
import requests
import datetime



app = Flask(__name__)


X_GEWE_TOKEN = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

def updatePlayerElo(name_b, name_w, result, gameId):
    # 四位棋手的对局得分S，胜利为1，失败为0
    if result == "b":
        S_b = 1
        S_w = 0
    else:
        S_b = 0
        S_w = 1

    # 对局数自增，并计算两队平均等级分，并计算每个棋手的系数K。
    ave_b = 0
    ave_w = 0
    K_b = []
    K_w = []
    n = len(name_b)
    for i in range(n):
        player[name_b[i]]["gameCount"] += 1
        player[name_w[i]]["gameCount"] += 1
        ave_b += player[name_b[i]]["rank"]
        ave_w += player[name_w[i]]["rank"]
        K_b.append(getK(player[name_b[i]]["gameCount"]))
        K_w.append(getK(player[name_w[i]]["gameCount"]))
    ave_b /= n
    ave_w /= n


    # 双方获胜概率，以等级分平均计算
    P_b = 1 / (1 + 10 ** ((ave_w - ave_b) / 400))
    P_w = 1 - P_b

    # 计算每个棋手的等级分，并生成数据库更新语句。
    _now = int(datetime.datetime.now().now().timestamp() - 0.5)
    sql = ""
    for i in range(n):
        player[name_b[i]]["rank"] += K_b[i] * (S_b - P_b)
        player[name_w[i]]["rank"] += K_w[i] * (S_w - P_w)
        player[name_b[i]]["updateTime"] = _now
        player[name_w[i]]["updateTime"] = _now
        sql += "UPDATE t_rank SET rank = %f, gameCount = %d, updateTime = %d WHERE playername = '%s';" % (player[name_b[i]]["rank"], player[name_b[i]]["gameCount"], _now, player[name_b[i]]["playername"])
        sql += "UPDATE t_rank SET rank = %f, gameCount = %d, updateTime = %d WHERE playername = '%s';" % (player[name_w[i]]["rank"], player[name_w[i]]["gameCount"], _now, player[name_w[i]]["playername"])

    # 更新到数据库
    conn = sqlite3.connect('elorank.db')
    cursor = conn.cursor()
    cursor.executescript(sql)
    cursor.execute("INSERT INTO t_game (gameId, 'data') VALUES ('%s', '%s');" % (gameId, game[gameId]))
    conn.commit()
    cursor.close()
    conn.close()
    return {
        "code": 200,
        "msg": "导入成功。"
    }

# 发送文本消息
def gewe_postText(appId, toWxid, content, ats=None):
    url = "http://api.geweapi.com/gewe/v2/api/message/postText"
    payload = json.dumps({
        "appId": appId,
        "toWxid": toWxid,
        "ats": ats,
        "content": content
    })
    headers = {
        'X-GEWE-TOKEN': X_GEWE_TOKEN,
        'Content-Type': 'application/json'
    }
    return requests.request("POST", url, headers=headers, data=payload)

# 系数策略。
def getK(gameCount):
   if gameCount <= 5:
      return 100
   elif gameCount <= 20:
      return 50
   else:
      return 20


def getInfoByWxid(wxid):
    if wxid not in wxid_map:
        return "您没注册"
    p = wxid_map[wxid]
    return '''棋手名：%s
等级分：%f
对局数：%d
更新时间：%s
野狐名：%s
弈客名：%s''' % (
    p["playername"],
    p["rank"],
    p["gameCount"],
    datetime.datetime.fromtimestamp(p["updateTime"]).strftime("%Y-%m-%d"),
    p["yehu_name"] if p["yehu_name"] else "未绑定",
    p["yike_name"] if p["yike_name"] else "未绑定"
)

# 注册新棋手
def addPlayer(wxid, playername, initialRank):
    if wxid in wxid_map:
        return {
            "code": 400,
            "msg": "您已注册"
        }

    if playername in player:
        return {
            "code": 400,
            "msg": "同名棋手已经存在。"
        }
    
    # 添加到数据表
    conn = sqlite3.connect('elorank.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO t_rank (playername, 'rank', gameCount, updateTime, wxid) VALUES ('%s', %s, 0, 0, '%s');" % (playername, initialRank, wxid))
    conn.commit()
    cursor.close()
    conn.close()

    p = {
        'playername': playername,
        'rank': float(initialRank), 
        'gameCount': 0, 
        'updateTime': int(datetime.datetime.now().now().timestamp() - 0.5),
        'wxid': wxid,
        'yike_name': None,
        'yehu_name': None,
        'tx_name': None
    }
    player[playername] = p
    wxid_map[wxid] = p
    return {
        "code": 200,
        "msg": "添加成功。"
    }

# 记录弈客对局
def yikeImport(yikeGameId):
    url = "https://game-server.yikeweiqi.com/game/info?id=%s&sgf_option=true&players_option=true&setting_option=true&clock_option=true" % (yikeGameId)
    headers = {
        'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxMTM0Nzk0LCJhcHBfaWQiOjEsImlhdCI6MTY3ODE5OTMyMywiaXNzIjoib25saW5lLWdhbWUifQ.YT_AXBUChk8l0r3BwHuSqzKwAPpUY45s6TXVD8pl6OA',
    }

    response = requests.request("GET", url, headers = headers)
    try:
        game_obj = json.loads(response.text)
    except json.JSONDecodeError as e:
        return {
            "code": 400,
            "msg": "读取失败请手动检查。"
        }
    if "data" not in game_obj or not game_obj["data"]:
        return {
            "code": 400,
            "msg": "读取失败请手动检查。"
        }
    
    # 判断人数是否相等。
    n = len(game_obj["data"]["players"]["blacks"])
    if n != len(game_obj["data"]["players"]["whites"]):
        return {
            "code": 400,
            "msg": "双方人数不相等。"
        }
    
    # 得到棋手的弈客名字，并判断是否在统计范围内。
    name_b = []
    name_w = []
    for i in range(n):
        nb = game_obj["data"]["players"]["blacks"][i]["name"]
        nw = game_obj["data"]["players"]["whites"][i]["name"]
        if nb not in yike_map:
            return {
                "code": 400,
                "msg": "黑方棋手[%s]不在统计范围之内。" % (nb)
            }
        if nw not in yike_map:
            return {
                "code": 400,
                "msg": "白方棋手棋手[%s]不在统计范围之内。" % (nw)
            }
        name_b.append(yike_map[nb]["playername"])
        name_w.append(yike_map[nw]["playername"])

    # 判断这个对局是否已经存在
    gameId = "yk_" + yikeGameId
    if gameId in game:
        return {
            "code": 400,
            "msg": "对局已经被统计。" 
        }
    game[gameId] = response.text

    # 开始时间
    begin_at = game_obj["data"]["began_at"]
    # 结果
    result = game_obj["data"]["result"]

    return updatePlayerElo(name_b, name_w, result[0], gameId)

# 记录野狐对局
def yehuImport(yehuGameId):
    # 根据id的到棋局信息并解析。
    url = "https://h5.foxwq.com/yehuDiamond/chessbook_local/FetchChessSummaryByChessID?chessid=%s" % (yehuGameId)
    response = requests.request("GET", url)
    try:
        game_obj = json.loads(response.text)
    except json.JSONDecodeError as e:
        return {
            "code": 400,
            "msg": "读取失败请手动检查。"
        }
    if "chesslist" not in game_obj or not game_obj["chesslist"]:
        return {
            "code": 400,
            "msg": "读取失败请手动检查。"
        }
    # 对局双方野狐名字。
    blacknick = game_obj["chesslist"]["blacknick"]
    whitenick = game_obj["chesslist"]["whitenick"]
    if blacknick not in yehu_map:
        return {
            "code": 400,
            "msg": "黑方棋手[%s]不在统计范围之内。" % (blacknick)
        }
    if whitenick not in yehu_map:
        return {
            "code": 400,
            "msg": "白方棋手[%s]不在统计范围之内。" % (whitenick)
        }
    # 判断是否已经被统计。
    gameId = "yh_" + yehuGameId
    if gameId in game:
        return {
            "code": 400,
            "msg": "对局已经被统计。" 
        }
    game[gameId] = response.text
    # 更新棋手elo分
    return updatePlayerElo(
        [yehu_map[blacknick]["playername"]], 
        [yehu_map[whitenick]["playername"]], 
        "b" if game_obj["chesslist"]["winner"] == 1 else "w", 
        gameId
        )

# 绑定其他平台账号,
def bindPlatformAccount(wxid, platform, accountName):
    if wxid not in wxid_map:
        return {
            "code": 400,
            "msg": "你未注册。"
        }
    if platform == "yehu":
        plat_map = yehu_map
        col_name = "yehu_name"
    elif platform == "yike":
        plat_map = yike_map
        col_name = "yike_name"
    if accountName in plat_map:
        return {
            "code": 400,
            "msg": "[%s]已经被其他棋手绑定" % (accountName)
        }
    # 更新到数据库
    conn = sqlite3.connect('elorank.db')
    cursor = conn.cursor()
    sql = "UPDATE t_rank SET %s = '%s' WHERE playername = '%s';" % (col_name, accountName, wxid_map[wxid]["playername"])
    cursor.execute(sql)
    conn.commit()
    cursor.close()
    conn.close()
    wxid_map[wxid][col_name] = accountName
    plat_map[accountName] = wxid_map[wxid]
    return {
        "code": 200,
        "msg": "绑定[%s]成功。" % (accountName)
    }


@app.route('/hello', methods=['GET', 'POST'])
def print_request_body():
    # 获取请求体的内容
    req_json = request.get_data().decode('utf-8')
    obj = json.loads(req_json)
    if obj["TypeName"] == "AddMsg":
        appId = obj["Appid"]
        msgType = obj["Data"]["MsgType"]
        FromUserName = obj["Data"]["FromUserName"]["string"]
        ToUserName = obj["Data"]["ToUserName"]["string"]
        string = obj["Data"]["Content"]["string"]
        temp = string.split(":\n")
        if len(temp) > 1:
            wxid = temp[0]
            string = temp[1]
        else:
            wxid = FromUserName
        strlist = string.split("#")

        if msgType == 1: # 普通消息
            if strlist[0] == "菜单":
                content = "功能菜单：\n注册新棋手\n绑定账号\n我的信息\n查看等级分\n录入\n（输入命令查看更多帮助）"
                res = gewe_postText(appId, FromUserName, content)
            elif strlist[0] == "注册新棋手":
                if len(strlist) == 3 and strlist[2].isdigit():
                    content = addPlayer(wxid, strlist[1], strlist[2])["msg"]
                    gewe_postText(appId, FromUserName, content)
                else:
                    content = "注册新棋手格式：\n注册新棋手#棋手名字#初始等级分\n如：\n注册新棋手#张三#1500"
                    gewe_postText(appId, FromUserName, content)
            elif strlist[0] == "绑定账号":
                content = "绑定野狐账号#野狐名字\n绑定弈客账号#弈客名字\n例：\n绑定野狐账号#潜伏\n或：\n绑定弈客账号#唐嘉雯"
                gewe_postText(appId, FromUserName, content)
            elif strlist[0] == "绑定野狐账号":
                if len(strlist) == 2:
                    content = bindPlatformAccount(wxid, "yehu", strlist[1])["msg"]
                    gewe_postText(appId, FromUserName, content)
                else:
                    connect = "格式：\n绑定野狐账号#野狐\n例：\n绑定野狐账号#潜伏"
                    gewe_postText(appId, FromUserName, content)
            elif strlist[0] == "绑定弈客账号":
                if len(strlist) == 2:
                    content = bindPlatformAccount(wxid, "yike", strlist[1])["msg"]
                    gewe_postText(appId, FromUserName, content)
                else:
                    connect = "格式：\n绑定弈客账号#弈客名\n例：\n绑定弈客账号#唐嘉雯"
                    gewe_postText(appId, FromUserName, content)
            elif strlist[0] == "我的信息":
                content = getInfoByWxid(wxid)
                gewe_postText(appId, FromUserName, content)
            elif strlist[0] == "查看等级分":
                elo10 = sorted(player.items(), key=lambda item: item[1]["rank"], reverse=True)[:10]
                content = "名字\t等级分\t对局数\t更新时间\n"
                for item in elo10:
                    content += "%s\t%d\t%s\t%s\n" % (item[0], int(item[1]["rank"] + 0.5), item[1]["gameCount"], datetime.datetime.fromtimestamp(int(item[1]["updateTime"])).strftime("%Y-%m-%d"))
                gewe_postText(appId, FromUserName, content)
        elif msgType == 49:   # 链接或引用链接
            # 处理转义
            xml = string.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            # 解析 XML 数据，查找 <type> 标签
            root = ET.fromstring(xml)
            type_element = root.find('.//type')
            title = root.find('.//title')
            if type_element.text == "57":    # 引用
                refermsg = root.find('.//refermsg')
                reftype = refermsg.find('type').text
                if reftype == "49":  # 引用一个链接
                    if title.text == "记录":
                        refcontent = refermsg.find('content').text
                        refcontent = refcontent.replace("&lt;", "<")
                        refcontent = refcontent.replace("&rt;", ">")
                        refroot = ET.fromstring(refcontent)
                        type_element = refroot.find('.//type') 
                        if type_element.text == "5":    # 链接
                            url = refroot.find('.//url').text.replace("&amp;", "&")
                            parsed_url = urlparse(url)
                            domain = parsed_url.netloc
                            params = parse_qs(parsed_url.query)
                            if domain == "h5.foxwq.com":    # 野狐
                                chessid = params["chessid"][0]
                                res = yehuImport(chessid)
                                gewe_postText(appId, FromUserName, res["msg"])
                                print(res)
                            elif domain == "home.yikeweiqi.com":    # 弈客
                                fragment = parsed_url.fragment
                                chessid = fragment.split("/")[2]
                                res = yikeImport(chessid)
                                gewe_postText(appId, FromUserName, res["msg"])
                            else:
                                print(domain, url)
                else:
                    print("引用其他")

        elif msgType == 51:     # 似乎是同步消息，逻辑上忽略
            pass
        else:
            pass
            #print(msgType, string)

    return "123"

if __name__ == '__main__':
    # 加载数据表
    conn = sqlite3.connect('elorank.db')
    cursor = conn.cursor()

    # 查询选手rank分，保存为字典
    cursor.execute("SELECT playername, rank, gameCount, updateTime, wxid, yike_name, yehu_name, tx_name FROM t_rank;")
    rows = cursor.fetchall()
    player = { 
        row[0]: {
            'playername': row[0],
            'rank': float(row[1]),
            'gameCount': int(row[2]),
            'updateTime': int(row[3]),
            'wxid': row[4],
            'yike_name': row[5],
            'yehu_name': row[6],
            'tx_name': row[7]
        } for row in rows 
     }

    # 查询所有对局，保存为字典
    cursor.execute("SELECT gameId, data FROM t_game;")
    rows = cursor.fetchall()
    game = { row[0]: row[1] for row in rows }

    # 建立四个平台名与选手名的映射。
    wxid_map = {}
    yike_map = {}
    yehu_map = {}
    tx_map = {}
    for key in player.keys():
        value = player[key]
        if value["wxid"]:
            wxid_map[value["wxid"]] = value
        if value["yike_name"]:
            yike_map[value["yike_name"]] = value
        if value["yehu_name"]:
            yehu_map[value["yehu_name"]] = value
        if value["tx_name"]:
            tx_map[value["tx_name"]] = value

    # 关闭游标和连接
    cursor.close()
    conn.close()

    app.run(debug=True, host='0.0.0.0', port=5000)
