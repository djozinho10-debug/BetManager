from src.api_football import _asian_total_result
assert _asian_total_result("over",2.5,3)=="WIN"
assert _asian_total_result("under",2.5,3)=="LOSS"
assert _asian_total_result("under",2.75,3)=="HALF LOSS"
assert _asian_total_result("over",2.75,3)=="HALF WIN"
assert _asian_total_result("under",3.0,3)=="VOID"
print("Liquidação asiática OK")
