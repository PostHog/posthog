"""Hashes of every template text the frontend rendered before templates moved to the backend.

A scout created back then has no template record, so the sync claims it only when its text, with the scanner id
replaced by `{scanner_id}`, hashes to one of these. Generated from each revision of `scannerScout.ts` in git
history; the list is closed, since scouts created since then are claimed when they are created.
"""

from products.replay_vision.backend.scout_templates import ScoutTemplateKey

LEGACY_TEMPLATE_BODY_HASHES: dict[ScoutTemplateKey, frozenset[str]] = {
    ScoutTemplateKey.VARIANT_ANALYSIS: frozenset(
        {
            "5f04868344a85dbed0a916b2dec9597bde46713ada28ca044a034c8f9ce9eec2",
            "c190c0c9648bab8e0b81ec6782f802361bc528c7f5fde00071859b2e6b293802",
            "c697a9df291dfa53438a17ca9382bdabfb7e7bfe53229eba31983d8205e255e3",
            "d211d37dbf618617e6dc6b2a2f6f68b814887066cbf1cb1aea7a300a825ce30b",
        }
    ),
    ScoutTemplateKey.DAILY_DIGEST: frozenset(
        {
            "147328970f8dc0c108ebbc94eb58d4a43779a7490bcfc9a5a2159f70e4c43f66",
            "1fc8d2b75e83ef5de19877f5411a903b1932c40e3ecffba07a153934b6c0202b",
            "4253c65303a272859d19b5be048517e7280c1947a5fae0a8e9ca8b70b917b08d",
            "4feb5ecdf83923e78c5c291d683b0ed97a0974c88a2b42bc01fbe387cecb4313",
            "589d3fc317700106b8928915779b7ca8fa1f6dc28c2077a1c6b203b8b7b14e3e",
            "63135ece0b23ca84935e40922e4ebf048a0cd158352191b82792e1bab4912094",
            "84e1f5374195175a630ee120cef681dc918c8da8bedf3f23a572c29cf1c51252",
            "975f8e06c00c9dcf71234d5785e70425159522bd30f58f1fb27d3bcfc145b025",
            "d30fe685b23f614efb20f297744e0750f526cac0fbab97ce088eca62ab8468ea",
        }
    ),
    ScoutTemplateKey.ROOT_CAUSE: frozenset(
        {
            "04a276ff5f35f012498e1b3932bdb35e9b65fb9229b72942cc6190bd46e72e40",
            "0da10a5607466066b6aa3232bebd42d7ce06383b34d2318caa0fde0b5d79f294",
            "7873fa79054291f30daeaf109b5f330aa8ce2247d62dcb0e668f0bee2cfff5a9",
            "d37a68088232c939d082c5eff2ef37d171c477ed26c115cabc89abc66765f2ea",
            "da1d33ebc4244292d8f666fa02a77ef01bd40bca0ee38467198f959394c4b011",
            "e204d29c68c7c960b8f364f0b4a241f08d0722f135031feb3206678053a47194",
        }
    ),
    ScoutTemplateKey.WEEKLY_THEMES: frozenset(
        {
            "183517f96582c2d46ed9bcd12b081469e2540ea42fae6358b22d8d50cc2fb5e1",
        }
    ),
    ScoutTemplateKey.TREND_WATCH: frozenset(
        {
            "03665ac2d3da9bdb1a1b48eea96a2e4615a95eaa80fdb1f3bafd38cb80235f2c",
            "0cf0c62c4d3086898fc928c4c0c379f172c0d6b7af28e5e849964ad588671a6e",
            "1401e2a660c7dfb909d17cf0686c476a47d113040782f8cbe23c0b9229c72b7f",
            "1582bf1ff5d59c152fb69a53fa216cf571f3a132a8c5bb6b2205adffbeff922c",
            "15fe2d682b0372038d36fee88ab351044d7fd4be40880f35f1ad73d6950856cf",
            "1c6fd099857c8551707dd863168e423661bfbedcd9755adf483a78287479c4fa",
            "22dab6f93f948f0029819c8561418604826aac0bc1adafcc7fba96518323eebe",
            "35e7790c39890b469a3ff0b020bd567cce6ff46e19d9562e318b05cf9bed7886",
            "3988e61692a6eea90c4ad2230a256a9338e802d9ca6e6ca3c05e7499642b5562",
            "41d4382733b9d4063dcf39ce1774c92d34dbdb2d644315c9244b3cc1b4a2ea95",
            "43763ef230e1768082848b9633223adce2d760ef5549dcb519354c64aeaec950",
            "4f4020338d7d5ba6237dc544b9ded608a312c58165917b943f8a4e3df5c618ab",
            "52496460168ee7a29a5b4c16e351e0b1c82acc02694baf2dc5a754dba2524836",
            "5346bd2b021bf1c58380a36ec39d9ca17527cde7b9e14da3dba717f6f8c26190",
            "5787d0ac4806179f70fc26200994bcd7e75f6dbb6b4cd5677a730b0c2c8db68e",
            "5920eeed7b55d9679e73a3cee4a1b26b5fa5dceda2217c42807b091d7b241888",
            "5dabf092a635ee6198ceb2adb9eb8231f9bbd174cb00f0e8eb5a775123686f46",
            "613ddf5a4ed5477f918f2429193df78186dce5236fa8972c3ad4a87bdec36110",
            "614c12e263377218b7d9c35142cffc8a87ce3288da9180943ba2faf4614954c7",
            "6ed745c6b6137b8245c26be201b69a60fe00f81d2beda95a411430be7889abc2",
            "730fde4283f001c32095664419ce67354fbbeb81adb97fd27c1516624078b595",
            "7488fb06fb534d68b634131f20c5709d80b37897ac1d48ba8e6f0cccc81d30d9",
            "82da0c95a4ef7c71f6649d9b3349d523db3f95564b8eadc180d376b29caf5b68",
            "8d3cc5631b74618c1611c030f2fb05f1b01e7a9df7131f6099915b6371e46828",
            "91e8616158cfc9e449f49e773d9266271ff948a360a3a785dfdaa4832880e69a",
            "956e6c41554e394508460f74afb50155ed67d3935c318af3108fe620b87e046b",
            "99434ee3b8b48541d63456cae5de788e1f0209dee00e73b8b538d948e1ec940e",
            "9a406c069013ff80dc055a18238d31df12cf58fbe210712e5aefd6005e26e9d7",
            "b33d5133e4a2e95a0bc1aa82c0ddfa7838092eaa9e79dee8a91407f6ef4a550d",
            "b9f17d897fd4b8ef7775769890f49d705cd9243336254e3d9df5f80b1b75e0ac",
            "c0d40c08c8ca784d013d6bb600ae9757de22b06ec298b5aea4d1f717952569d2",
            "c5ad55070dc07c14f3da5da3425adc33ae0b8769fac0dedb29a177afd0353081",
            "cb4ab58e415eb77b5b1a2c3ef8326e62243d84e3b580e719c069fd36c5c0cfa0",
            "d3d36b285212d45531c02a435fce4106265df3c4b8c5d80da449ed6809487d71",
            "dc4f9b431bd560fe65a929269a1d635094811b8802b4679a23086854d13eb35e",
            "eaebc938caf1027e694ad8535c23f063a72ea890c4e7fbce29406736811a062b",
        }
    ),
    ScoutTemplateKey.NEW_ISSUES: frozenset(
        {
            "045dd66a593c5b2d81d49465b4cc1a5d04a10e4262831c35ee9f9ef9b9c1ce8f",
            "08f54e6a694ac2bbbb9b575e62ad7558610d7f85f0b8b475c07536c87b8bcd69",
            "0a26f1b9839c49418c57366dbbf15acdef5a8976353c04dbe08eb840e18d5775",
            "28d3dc9add0406321e1abc5c32e1d29a262be6875bdf1f9ec6605b5558d08b83",
            "3707c2599b42912d92ad05cf4ccf053a3820176d082e5958be6ce30ece6960ea",
            "4ec93cdb7f5f076d7d76caa3d5b7b3adea3bee2196397862cc1cbbf6db984a15",
            "ab12f6f00f888917832d31e7688bbd445143079caa9e5bc033293854b9d54f86",
            "ebc008a2b7ac32031174bbacc35df87c99a53ca3a8df60898acef98919ff85fc",
            "f9251647d74a8c2b66afdd8df8d0ecaccf9b2180f77919db091b8d03faae2773",
        }
    ),
}
