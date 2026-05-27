import time
from pupremote import PUPRemoteSensor

print('Import OK')
pr = PUPRemoteSensor(power=True)
pr.add_channel('obj', to_hub_fmt='b')
pr.add_channel('cmd', to_hub_fmt='b')
print('PUPRemoteSensor + 2 channels OK')

connected_attr_seen = False
for i in range(15000):
    pr.process()
    time.sleep_ms(2)
    if (i % 500) == 0:
        is_conn = getattr(pr, 'connected', None)
        print('tick', i, 'connected=', is_conn)
    if getattr(pr, 'connected', False):
        if not connected_attr_seen:
            print('CONECTAT! la tick', i)
            connected_attr_seen = True

print('Final connected attr=', getattr(pr, 'connected', None))
print('dir(pr)=', dir(pr))
