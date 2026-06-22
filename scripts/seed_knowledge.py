"""
知识库种子数据导入脚本
首次启动时自动导入基础 FAQ
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.db.base import async_session, init_db, compute_embedding
from server.db.models import KnowledgeItem, KnowledgeEmbedding
from sqlalchemy import select

# 基础 FAQ 种子数据
SEED_FAQ = [
    # 面料相关
    ("这件衣服会缩水吗？",
     "亲亲～这款我们已经做过预缩处理了，正常洗涤不会缩水的哦。建议冷水轻柔洗涤、悬挂晾干，这样穿更久呢 😊",
     "面料", "seed"),

    ("是什么面料的？",
     "这款是天丝混纺的哦～摸起来滑滑的很亲肤，透气性也超好，夏天穿不会闷。具体的面料成分可以在商品详情页看到详细比例～",
     "面料", "seed"),

    ("衣服透不透？",
     "亲亲白色/浅色款会稍微有一点透，建议穿浅色内衣或者加个内搭哦～深色款完全没问题的！",
     "面料", "seed"),

    ("穿久了会起球吗？",
     "正常穿着和洗涤的话不太会起球呢～不过摩擦多的地方（比如背包带下面）可能会有轻微起球，用剃球器处理一下就OK啦 💕",
     "面料", "seed"),

    ("会褪色吗？",
     "深色款第一次洗涤会有轻微浮色是正常的哦，建议深色浅色分开洗涤～我们家用的都是环保活性染料，洗几次就稳定啦",
     "面料", "seed"),

    # 尺码相关
    ("选什么尺码？",
     "亲亲方便说下身高体重吗？我帮你选最合适的码～也可以参考详情页的尺码表，量下自己的三围对照着选更准哦",
     "尺码", "seed"),

    ("偏大还是偏小？",
     "这款是标准码的哦～按照平时的尺码选就行。如果不确定的话可以告诉我你的身高体重，我帮你确认一下！",
     "尺码", "seed"),

    ("我160/50kg穿什么码？",
     "宝你这个身材穿M码应该刚刚好！喜欢宽松一点的可以选L哦～不过每个人身型不太一样，可以参考尺码表再确认下 😊",
     "尺码", "seed"),

    # 物流相关
    ("什么时候发货？",
     "现货的话48小时内发出哦～预售款需要等7-15天呢，具体可以看商品页面显示的发货时间。发了马上给你单号！",
     "物流", "seed"),

    ("多久能到货？",
     "一般发出后3-5天到呢～主要看你的地址远近。江浙沪一般2-3天，偏远地区5-7天。快递的事说不准，到不了随时找我！",
     "物流", "seed"),

    ("发什么快递？",
     "默认发中通/圆通哦～如果你要发顺丰的话可以补差价，加¥10发顺丰标快。偏远地区默认发邮政哈",
     "物流", "seed"),

    ("能不能改地址？",
     "还没发货的话可以改哦！亲亲把新地址发给我，我帮你改～已经发货了就改不了了呢 😢",
     "物流", "seed"),

    # 售后相关
    ("怎么退货？",
     "7天内可以无理由退货哦～亲亲先申请退货退款，然后把衣服原包装寄回来就行。收到后检查没问题就给你通过退款 💕",
     "售后", "seed"),

    ("退货运费谁出？",
     "质量问题我们承担来回运费，非质量问题（比如不喜欢/大小不合适）需要亲亲自己承担退货运费哦～",
     "售后", "seed"),

    ("收到货发现有问题怎么办？",
     "啊真的抱歉！方便拍个照片给我看下吗？我马上帮你处理～该退退该换换，一定让你满意！😢",
     "售后", "seed"),

    ("可以换货吗？",
     "可以的呀！告诉我你想换哪个颜色/尺码，我帮你看有没有库存。你先把原来的寄回来，我们收到后马上发新的给你～",
     "售后", "seed"),

    # 价格/活动
    ("有没有优惠？",
     "亲亲现在的价格已经是活动价了呀～不过满199可以包邮！另外关注店铺还有新人优惠券可以领哦 💕",
     "活动", "seed"),

    ("能便宜点吗？",
     "哎呀宝，这个价已经是底线啦 😭 不过满199包邮，可以搭配其他喜欢的款一起带走省个运费！",
     "活动", "seed"),

    ("有优惠券吗？",
     "有的呢！关注店铺可以领新人券，另外满299减20的活动也在进行中。具体可以在店铺首页领哦～",
     "活动", "seed"),

    # 洗护相关
    ("怎么洗？",
     "这款建议冷水手洗或洗衣机的轻柔模式哦～不要用热水和强力洗涤，悬挂晾干就好啦。深色衣服第一次建议单独洗！",
     "洗护", "seed"),

    ("可以用洗衣机吗？",
     "可以的呀～放洗衣袋里用轻柔模式洗就没问题。但不要和牛仔裤这些硬的东西一起洗哦，会磨到衣服的",
     "洗护", "seed"),

    ("需要熨烫吗？",
     "这款面料不太容易皱，晾的时候拉平整一点基本不用熨呢。如果皱了低温熨烫就好，不要太高温哦～",
     "洗护", "seed"),
]


async def seed():
    """导入种子数据"""
    await init_db()

    async with async_session() as db:
        # 检查是否已有数据
        result = await db.execute(
            select(KnowledgeItem).where(KnowledgeItem.source == "seed").limit(1)
        )
        if result.first():
            print("Seed data already exists, skipping.")
            return

        count = 0
        for question, answer, category, source in SEED_FAQ:
            import uuid

            kid = str(uuid.uuid4())
            # 写入知识条目
            item = KnowledgeItem(
                id=kid,
                question=question,
                answer=answer,
                category=category,
                source=source,
                status="active",
            )
            db.add(item)

            # 写入向量
            embedding = compute_embedding(question + "\n" + answer)
            vid = str(uuid.uuid4())
            vec = KnowledgeEmbedding(
                id=vid,
                knowledge_id=kid,
                content=question + "\n" + answer,
                embedding=embedding,
                content_type="qa",
            )
            db.add(vec)
            count += 1

        await db.commit()
        print(f"Seeded {count} knowledge items.")


if __name__ == "__main__":
    asyncio.run(seed())
