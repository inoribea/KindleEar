#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#投递相关功能，GAE平台的cron会每个小时调用请求一次Deliver()

from collections import defaultdict
from flask import Blueprint, render_template, request
from flask_babel import gettext as _
from apps.back_end.task_queue_adpt import create_delivery_task
from apps.base_handler import *
from apps.back_end.db_models import *
from apps.utils import local_time

bpDeliver = Blueprint('bpDeliver', __name__)

#判断需要推送哪些书籍
#GAE的cron调度的请求会有一个HTTP标头：X-Appengine-Cron: true
#cron调度的请求不带任何参数，带参数的是高级设置里面的"现在推送"功能发起的
@bpDeliver.route("/deliver")
def Deliver():
    userName = request.args.get('u')
    
    if userName: #现在投递【测试使用】，不需要判断时间和星期
        recipeList = request.args.get('id', '').split(',')
        return SingleUserDelivery(userName, recipeList)
    else: #如果不指定userName，说明是定时cron调用
        return MultiUserDelivery()

#判断所有账号所有已订阅书籍，确定哪些需要推送
def MultiUserDelivery():
    bkQueue = defaultdict(list)
    sentCnt = 0
    return
    for user in KeUser.select().where(KeUser.enable_send == True):
        for book in user.get_booked_recipe():
            #先判断当天是否需要推送
            day = local_time('%A', user.timezone)
            userDays = user.send_days
            if book.send_days: #如果特定Recipe设定了推送时间，则以这个时间为优先
                if day not in book.send_days:
                    continue
            elif userDays and day not in userDays: #user.send_days为空也表示每日推送
                continue
                
            #时间判断
            hr = int(local_time("%H", user.timezone)) + 1
            if hr >= 24:
                hr -= 24
            if book.send_times:
                if hr not in book.send_times:
                    continue
            elif user.send_time != hr:
                continue
            
            #到了这里就是需要推送的
            queueOneBook(bkQueue, user, book.recipe_id, book.separated)
            sentCnt += 1
    flushQueueToPush(bkQueue)
    return "Put {} books into queue.".format(sentCnt)

#判断指定用户的书籍和订阅哪些需要推送
#userName: 账号名
#recipeList: recipe id列表，id格式：custom:xx,upload:xx,builtin:xx，为空则推送指定账号下所有订阅
def SingleUserDelivery(userName: str, recipeList: list):
    user = KeUser.get_one(KeUser.name == userName)
    if not user or not user.kindle_email:
        return render_template('autoback.html', tips=_('The username does not exist or the email is empty.'))

    sent = []
    #这里不判断特定账号是否已经订阅了指定的书籍，只要提供就推送
    if recipeList:
        recipesToPush = list(filter(bool, map(user.get_booked_recipe, recipeList)))
    else: #推送特定账号所有订阅的书籍
        recipesToPush = user.get_booked_recipe()
    
    bkQueue = {user.name: []}
    for bkRecipe in recipesToPush: #BookedRecipe实例
        queueOneBook(bkQueue, user, bkRecipe.recipe_id, bkRecipe.separated)
        sent.append(bkRecipe.title)
    self.flushQueueToPush(bkQueue)
    
    if sent:
        tips = (_("The following recipe has been added to the push queue.") 
            + '<br/><p>' + '<br/>'.join(sent)) + '</p>'
    else:
        tips = _("There are no books to deliver.")

    return render_template('autoback.html', tips=tips)

#根据设置，将书籍预先放到队列之后一起推送，或马上单独推送
#queueToPush: 用来缓存的一个字典，用户名为键，元素为recipeId列表
#user: KeUser实例
#recipeId: Recipe Id, custom:xx, upload:xx, builtin:xx
#separated: 是否单独推送
def queueOneBook(queueToPush: defaultdict, user: KeUser, recipeId: str, separated: bool):
    if separated:
        create_delivery_task({"userName": user.name, "recipeId": recipeId})
    else:
        queueToPush[user.name].append(recipeId) #合并推送

#启动推送队列中的书籍
def flushQueueToPush(queueToPush: defaultdict):
    for name in queueToPush:
        create_delivery_task({'userName': name, 'recipeId': ','.join(queueToPush[name])})


#用于除GAE以外的托管环境，使用cron执行此文件即可启动推送
if __name__ == '__main__':
    MultiUserDelivery()