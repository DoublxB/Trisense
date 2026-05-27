"""
Test minimal Pybricks: incarca asta in Pybricks Code IDE (slot nou)
si apasa RUN. Scopul: vedem daca Hub-ul detecteaza ESP-ul pe Port A
fara nimic altceva care sa interfereze.

Trebuie sa ai pupremote_hub.py incarcat pe Hub (ca al doilea fisier).
"""

from pybricks.hubs import PrimeHub
from pybricks.parameters import Port
from pybricks.tools import wait
from pupremote_hub import PUPRemoteHub

hub = PrimeHub()
print("Hub pornit OK")

print("Astept ESP pe Port A...")
for attempt in range(1, 11):
    try:
        pr = PUPRemoteHub(Port.A)
        pr.add_channel("obj", to_hub_fmt="b")
        pr.add_channel("cmd", to_hub_fmt="b")
        print("LPF2 OK la incercarea", attempt)
        break
    except OSError as e:
        print("Incercare", attempt, "esuata:", e)
        wait(1500)
else:
    print("ESP NU este detectat dupa 10 incercari.")
    print("Verifica: cablu LEGO, Port A, ESP alimentat, ESP ruleaza main.py")
    while True:
        wait(1000)

print("Comunicare activa. Citesc obj la fiecare 500ms...")
while True:
    try:
        obj = pr.call("obj")
        print("obj =", obj)
    except OSError as e:
        print("LPF2 pierdut:", e)
        break
    wait(500)
