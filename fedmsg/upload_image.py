#!/usr/bin/python

import fedmsg
import koji
import os
import shutil
import sys

mod = 'cloud-image-uploader'

def main(message):
    
    location = get_image(message)

    #Convert from qcow2 to raw
    if location.endswith('.qcow2'):
        newLocation = location[:6] + '.raw'
        os.system('qemu-img convert %s %s' % (location, (newLocation)))
        topic = 'image.qcow2.complete'
    else:
        newLocation = location
        topic = 'image.rawxz.complete'
    if message['topic'] == 'fedoraproject.org.prod.SOMETHING':
        #Upload to EC2
        os.system('uploader.py %s' % (newLocation))
        #fedmsg is inside uploader.py so no need to broadcast here

    move_image(newLocation, topic)

def get_image(message):
    #The message should have a koji task ID, from that we can get some data
    taskID = message
    conn = koji.ClientSession('http://koji.fedoraproject.org/kojihub')
    task = conn.getTaskInfo(taskID, request=True)
    #Download image and return location
    location = 0
    return location

def move_image(location, top):
    #Copy file(s) to right location
    moveLocation = '/mnt/alt.fedoraproject.org/pub/alt/cloud'
    shutil.move(location, moveLocation)
    #fedmsg tells that this exists
    fedmsg.publish(topic=top, modname=mod, msg={os.path.basename(location): moveLocation})

def update_site(location):
    """Have to work on this"""
    pass
