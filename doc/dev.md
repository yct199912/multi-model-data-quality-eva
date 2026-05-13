需要一个接口（Post接口），这个接口的认证方式为在header头里面加appKey与appSecret，这两个参数需要在.env文件里面配置，帮我配置下。
接口传参为数据仓库名称repoName, 所有者用户名userName, 评价分支名称branchName，数据库简介repoIntroduction，任务id:taskId
首先将下面的表格中repo = userName/repoName(由入参拼接)的记录删除:
content_accuracy_score、content_consistency_score、content_integrity_score、content_unq_score、repo_accuracy_score、repo_consistency_score、repo_effectiveness_score、repo_integrity_score、repo_timeliness_score、repo_unq_score
按给定的分支名称进行评价，如果分支名称为空则使用默认分支(master)进行评价。
数据获取方式如下
进行评价的的数据集文件通过GET调用拼接的网络地址获得:
网络地址拼接模板GITEA_BASE_URL + GITEA_FILE_OB
调用的时候需要在header的认证信息里面加上token信息:GITEA_TOKEN; 示例{"Authorization": "token {GITEA_TOKEN}"}
其中GITEA_BASE_URL、GITEA_FILE_OB、GITEA_TOKEN全都配置在了.env文件里面
需要将GITEA_FILE_OB中的{owner}替换为userName, {repo}替换为repoName, {filepath}为文件路径，初始为空
branchName需要被放在queryParams里面对应的字段为"ref"
调用之后会获取filepath文件夹下所有的文件信息，其中格式为dir的为文件夹
示例如下：[
    {
        "name": ".gitattributes",
        "path": ".gitattributes",
        "sha": "7b4129fc7039a4008645b56b47001c2661ee5b64",
        "last_commit_sha": "53b2a6f30188085e2ac7c20dbba2b17b558f080f",
        "type": "file",
        "size": 2469,
        "encoding": null,
        "content": null,
        "target": null,
        "url": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/contents/.gitattributes?ref=master",
        "html_url": "http://localhost:3000/17861406546/xyq0511/src/branch/master/.gitattributes",
        "git_url": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/git/blobs/7b4129fc7039a4008645b56b47001c2661ee5b64",
        "download_url": "http://localhost:3000/17861406546/xyq0511/raw/branch/master/.gitattributes",
        "submodule_git_url": null,
        "_links": {
            "self": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/contents/.gitattributes?ref=master",
            "git": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/git/blobs/7b4129fc7039a4008645b56b47001c2661ee5b64",
            "html": "http://localhost:3000/17861406546/xyq0511/src/branch/master/.gitattributes"
        }
    },
    {
        "name": "example",
        "path": "example",
        "sha": "aa4cf0d0f1fc3cdae0d50a698fa2bf56e38690c6",
        "last_commit_sha": "f0c8ac012f88439d97a698d3f0a9d98d657104cd",
        "type": "dir",
        "size": 0,
        "encoding": null,
        "content": null,
        "target": null,
        "url": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/contents/example?ref=master",
        "html_url": "http://localhost:3000/17861406546/xyq0511/src/branch/master/example",
        "git_url": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/git/blobs/aa4cf0d0f1fc3cdae0d50a698fa2bf56e38690c6",
        "download_url": null,
        "submodule_git_url": null,
        "_links": {
            "self": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/contents/example?ref=master",
            "git": "http://localhost:3000/api/v1/repos/17861406546/xyq0511/git/blobs/aa4cf0d0f1fc3cdae0d50a698fa2bf56e38690c6",
            "html": "http://localhost:3000/17861406546/xyq0511/src/branch/master/example"
        }
    }
]
其中example为文件夹，将{filepath}设置为"/example"之后调用这个接口可以获取到此文件夹下面的所有文件信息
将{filepath}设置为具体文件名之后可以获取具体文件，（注意中文要使用URL编码）
具体文件信息如下：
{
    "name": "Doc1.docx",
    "path": "example/Doc1.docx",
    "sha": "b0801827266505099880afd11393f92616dc700d",
    "last_commit_sha": "b32619cbae15dbf660d2257bed3c2bdc4c95a0e6",
    "type": "file",
    "size": 209837,
    "encoding": "base64",
    "content": "UEsDBBQABgAIAAA......AIQCj7AA=",
    "target": null,
    "url": "http://localhost:3000/api/v1/repos/17861406546/xyq05111/contents/example/Doc1.docx?ref=master",
    "html_url": "http://localhost:3000/17861406546/xyq05111/src/branch/master/example/Doc1.docx",
    "git_url": "http://localhost:3000/api/v1/repos/17861406546/xyq05111/git/blobs/b0801827266505099880afd11393f92616dc700d",
    "download_url": "http://localhost:3000/17861406546/xyq05111/raw/branch/master/example/Doc1.docx",
    "submodule_git_url": null,
    "_links": {
        "self": "http://localhost:3000/api/v1/repos/17861406546/xyq05111/contents/example/Doc1.docx?ref=master",
        "git": "http://localhost:3000/api/v1/repos/17861406546/xyq05111/git/blobs/b0801827266505099880afd11393f92616dc700d",
        "html": "http://localhost:3000/17861406546/xyq05111/src/branch/master/example/Doc1.docx"
    }
}
其中content信息为文件的base64编码。
使用深度优先搜索遍历对每个文件进行下述数据质量评价，与数据库插入操作。
所有的分均为百分制得分，保留两位小数。
1、首先对于文件首先进行格式分析。
2、调用模型（gemma-4-e4b）接口将文件输入给模型。
3、对相应格式的文件进行下面的评价步骤
如果是图像文件进行图像文件评价：
准确性：
图像内容准确性检测：使用模型(gemma-4-e4b)对图像文件的图像内容进行准确性评价打分：
（1）给模型图像内容准确性检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的图像内容准确性得分与图像内容准确性的评价内容。
（3）根据上述信息形成数据库表格content_accuracy_score的插入记录并插入到数据库中，eva_type字段为"image-content", file_type字段为"image", 
完整性：
无信息区域检测：使用模型(gemma-4-e4b)根据图像的无信息区域进行完整性评价打分：
（1）给模型无信息区域检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的完整性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_consistency_score的插入记录并插入到数据库中，eva_type字段为"image-noinfo", file_type字段为"image"。
无信息噪声检测：使用模型(gemma-4-e4b)根据图像的噪声信息进行完整性评价打分：
（1）并给模型无信息噪声检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的完整性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_consistency_score的插入记录并插入到数据库中，eva_type字段为"image-noise", file_type字段为"image"。
唯一性：
图内信息唯一性规则：使用模型(gemma-4-e4b)对图像的内容唯一性进行评价打分：
（1）给模型图内信息唯一性规则提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的图内信息唯一性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_unq_score的插入记录并插入到数据库中，eva_type字段为"image-content", file_type字段为"image"。
一致性：
图内信息一致性规则：使用模型(gemma-4-e4b)对图像的内容一致性进行评价打分：
（1）给模型图内信息一致性规则提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的图内信息一致性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_integrity_score的插入记录并插入到数据库中，eva_type字段为"image-content", file_type字段为"image"。
如果是文本文件进行文本文件评价：
准确性：
文本格式准确性检测：根据文件格式，使用模型(gemma-4-e4b)对文本文件的文本格式进行准确性评价打分：
（1）并给模型文本格式准确性检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的文件格式准确性得分与文件格式准确性的评价内容。
（3）根据上述信息形成数据库表格content_accuracy_score的插入记录并插入到数据库中，eva_type字段为"text-format", file_type字段为"text"。
文本内容准确性检测：根据文件内容，使用模型(gemma-4-e4b)对文本文件的文本内容进行准确性评价打分：
（1）并给模型文本内容准确性检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的文件内容准确性得分与文件内容准确性的评价内容。
（3）根据上述信息形成数据库表格content_accuracy_score的插入记录并插入到数据库中, eva_type字段为"text-content", file_type字段为"text"。
完整性：
无信息文本检测：使用模型(gemma-4-e4b)根据文本文件的无信息文本进行完整性评价打分：
（1）并给模型无信息文本检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的文本文件的无信息文本检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_consistency_score的插入记录并插入到数据库中，eva_type字段为"text-noinfo", file_type字段为"text"。
描述完整性检测：使用模型(gemma-4-e4b)对文本文件的描述完整性评价打分：
（1）并给模型描述完整性检测提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的文本文件的描述完整性得分、文件的描述完整性评价内容。
（3）根据上述信息形成数据库表格content_consistency_score的插入记录并插入到数据库中，eva_type字段为"text-desc", file_type字段为"text"。
唯一性：
文本信息唯一性规则：使用模型(gemma-4-e4b)对文本文件内容唯一性进行评价打分：
（1）并给模型文本信息唯一性规则提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的文本信息唯一性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_unq_score的插入记录并插入到数据库中，eva_type字段为"text-content", file_type字段为"text"。
一致性：
文本信息一致性规则：使用模型(gemma-4-e4b)对文本的内容一致性进行评价打分：
（1）并给模型文本信息一致性规则提示词、模型输出内容、输出格式提示词。
（2）记录模型输出的文本信息一致性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格content_integrity_score的插入记录并插入到数据库中，eva_type字段为"text-content", file_type字段为"text"。
注意：步骤(1)的提示词是从提示词文件中读取的。
psql评分记录表格描述(多个表格同一结构)：
{
	tableName: 'content_accuracy_score'|'content_consistency_score'|'content_unq_score'|'content_integrity_score',
	fields: {
		id: 'bigserial | PRIMARY KEY | 主键id(自增)',
		repo: 'VARCHAR(255) | 数据仓库地址(例:userName/repoName)',
		file_path: 'varchar(255) | 文件地址文件名(例:/example/file.docx)',
		score: 'numeric(10, 2) | 文件唯一性得分',
		file_type: 'varchar(10) | 文件类型(图像:iamge|文本:text)',
		eva_dsc: 'text | 文件准确性评价',
		deleted: 'int2 | 是否被删除(默认0)',
		eva_type: 'varchar(20) | 评价格式'
	}
}
提示词配置文件:
规则提示词:
图像:
完整性:
无信息区域检测:图像无纯色区域、纯色条带、内容无效区域，内容有效则得分score较高，否则得分score较低；规则得分满分为100。请对此图像进行图内信息完整性打分与评价。
无信息噪声检测:图像无噪声，检查图像是否存在无信息的噪声数据噪声越少得分score越高，否则score较低；规则得分满分为100。请对此图像进行图内信息完整性打分与评价。
唯一性:
图内信息唯一性规则:图像内容统一描述了一个事物，且信息丰富、描述内容不冗余则score较高，图像中存在许多冗余内容则得分score较低；规则得分满分为100。请对此图像进行图内信息唯一性打分与评价。
一致性:
图内信息一致性规则:图像内容统一描述了一个事物，且信息丰富、描述内容融洽则score较高，图像中存在许多冲突的描述内容或者不相关的描述内容则得分score较低；规则得分满分为100。请对此图像进行图内信息一致性打分与评价。
准确性:
图像内容准确性检测:图像需要准确描述一个事物或者事件、信息准确。图像准确度高则score较高，反之较低。请对此图像进行图像内容准确性打分与评价。
文本:
完整性:
无信息文本检测:对此文本文件进行非法字符检测、乱码检测、空格等无信息文本检测，最后统计正常部分占比*100作为这个规则的得分score。请据此对此文本文件进行分与评价。
描述完整性检测:文本内容描述完整性检测，统计完整性描述占比*100作为这个规则的得分score。请据此对此文本文件进行分与评价。
唯一性:
文本信息唯一性规则:文本中的描述信息统一且唯一。如果一个文本文件中存在许多冗余描述内容则信息唯一性得分较低；一个文本文件内容统一描述了一个事物，且信息丰富、不冗余则文本信息唯一性得分较高，规则得分满分为100。请据此对此文本文件进行分与评价。
一致性:
文本信息一致性规则:文本中的描述信息统一描述了一个事物，且信息丰富、描述内容融洽则score较高，文本中存在许多冲突的描述内容或者不相关的描述内容则得分score较低；规则得分满分为100。请据此对此文本文件进行分与评价。
准确性：
文本内容准确性检测:文本需要准确描述一个事物或者事件、信息准确、最好贴合文件名。文本准确度高则score较高，反之较低。请对此图像进行图像内容准确性打分与评价。
输出格式提示词:完成之后严格按照以下JSON格式返回结果，不要返回其他任何内容：格式为{"score": ${score}, "eva_content": ${eva_content}}，其中${score}为规则得分(百分制，保留两位小数的数字)，${eva_content}为相应的评价内容, 使用中文描述(字符串)。
请将上面这些提示词有规律有层次的放入到相应的提示词文件中。
------------------------------------------------------------------------------------------------------------------------------
在调用模型(gemma-4-e4b)评价一个数据仓库的时候，确保使用一个会话。
完成上述评价之后：
根据所有文件进行下面的评价与记录：
有效性：
（1）将数据仓库的简介(repoIntroduction)输入给模型(gemma-4-e4b)，输入有效性规则提示词，输出格式提示词。
（2）记录模型输出的数据仓库有效性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_effectiveness_score的插入记录并插入到数据库中，得分计入score，评价计入eva_dsc。
及时性：
（1）将及时性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的数据仓库及时性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_timeliness_score的插入记录并插入到数据库中，得分计入score，评价计入eva_dsc。
图间唯一性:
（1）将图间唯一性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的图间唯一性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_unq_score的插入记录并插入到数据库中, eva_rule_type = "inter-image-unq", 得分计入"score_model"字段，评价记入"eva_dsc"字段。
图间一致性:
（1）将图间一致性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的图间一致性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_integrity_score的插入记录并插入到数据库中, eva_rule_type = "inter-image-integrity"，得分计入"score_model"字段，评价记入"eva_dsc"字段。
文本间唯一性:
（1）将文本间唯一性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的文本间唯一性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_unq_score的插入记录并插入到数据库中, eva_rule_type = "inter-text-unq"， 得分计入"score_model"字段，评价记入"eva_dsc"字段。
文本间一致性:
（1）将文本间一致性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的文本间一致性评价得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_integrity_score的插入记录并插入到数据库中, eva_rule_type = "inter-text-integrity", 得分计入"score_model"字段，评价记入"eva_dsc"字段。
在提示词文件中增加下面的提示说明：
有效性规则:综合这次所有的文件，与上面的数据仓库简介，请进行整体有效性评分与评价。
及时性规则:综合这次所有文件请进行数据仓库的及时性评分与评价。
图间唯一性规则:综合这次评价的所有图像文件，进行图间唯一性评分与评价。
图间一致性规则:综合这次评价的所有图像文件，进行图间一致性评分与评价。
文本间唯一性规则:综合这次评价的所有文本文件，进行文本间唯一性评分与评价。
文本间一致性规则:综合这次评价的所有文本文件，进行文本间一致性评分与评价。
-----------------------------------------------------------------
根据所有文件进行下面的评价与记录：
下面所有向数据库中的插入操作：字段repo都为userName/repoName(用户名和仓库名的拼接，即接口入参的拼接)
图像：
综合图像内容准确性检测:
（1）将综合图像内容准确性检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合图像内容准确性检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_accuracy_score的插入记录并插入到数据库中, eva_rule_type = "imgself-accuracy"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合图像无信息区域检测:
（1）将综合图像无信息区域检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合图像无信息区域检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_consistency_score的插入记录并插入到数据库中, eva_rule_type = "imgself-consistency-region"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合图像无信息噪声检测:
（1）将综合图像无信息噪声检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合图像无信息噪声检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_consistency_score的插入记录并插入到数据库中, eva_rule_type = "imgself-consistency-noise"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合图内信息唯一性规则:
（1）将综合图内信息唯一性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合图内信息唯一性得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_unq_score的插入记录并插入到数据库中, eva_rule_type = "imgself-unq"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合图内信息一致性规则:
（1）将综合图内信息一致性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合图内信息一致性得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_integrity_score的插入记录并插入到数据库中, eva_rule_type = "imgself-integrity"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
文本：
综合文本格式准确性检测:
（1）将综合文本格式准确性检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合文本格式准确性检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_accuracy_score的插入记录并插入到数据库中, eva_rule_type = "textself-accuracy-format"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合文本内容准确性检测:
（1）将综合文本内容准确性检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合文本内容准确性检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_accuracy_score的插入记录并插入到数据库中, eva_rule_type = "textself-accuracy-content"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合文本无信息文本检测:
（1）将综合文本无信息文本检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合文本无信息文本检测测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_consistency_score的插入记录并插入到数据库中, eva_rule_type = "textself-consistency-noinfo"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合文本描述完整性检测:
（1）将综合文本描述完整性检测提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合文本描述完整性检测得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_consistency_score的插入记录并插入到数据库中, eva_rule_type = "textself-consistency-content"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合文本信息唯一性规则:
（1）将综合文本信息唯一性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合文本信息唯一性得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_unq_score的插入记录并插入到数据库中, eva_rule_type = "textself-unq"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
综合文本信息一致性规则:
（1）将综合文本信息一致性规则提示词、输出格式提示词输入给模型(gemma-4-e4b)。
（2）记录模型输出的综合文本信息一致性得分、相应的评价内容。
（3）根据上述信息形成数据库表格repo_integrity_score的插入记录并插入到数据库中, eva_rule_type = "textself-integrity"，得分记入"score_model"字段，评价记入"eva_dsc"字段。
在提示词文件中增加下面的提示说明：
图像:
综合图像内容准确性检测:综合这次评价的所有图像文件，进行总体图像内容准确性检测评分和评价。
综合完整性无信息区域检测:综合这次评价的所有图像文件，进行总体完整性无信息区域检测评分和评价。
综合完整性无信息噪声检测:综合这次评价的所有图像文件，进行总体完整性无信息噪声检测评分和评价。
综合图内信息唯一性规则:综合这次评价的所有图像文件，进行总体图内信息唯一性评分和评价。
综合图内信息一致性规则:综合这次评价的所有图像文件，进行总体图内信息一致性规则评分和评价。
文本：
综合文本格式准确性检测:综合这次评价的所有文本文件，进行总体文本格式准确性检测评分和评价。
综合文本内容准确性检测:综合这次评价的所有文本文件，进行文本内容准确性检测评分和评价。
综合完整性无信息文本检测:综合这次评价的所有文本文件，进行完整性无信息文本检测评分和评价。
综合完整性描述完整性检测:综合这次评价的所有文本文件，进行完整性描述完整性检测的评分和评价。
综合文本信息唯一性规则:综合这次评价的所有文本文件，进行文本信息唯一性评分和评价。
综合文本信息一致性规则:综合这次评价的所有文本文件，进行文本信息一致性评分和评价。
------------------------------------------------------------------------------------
查询数据库中的content_accuracy_score|content_consistency_score|content_integrity_score|content_unq_score四张表格
计算每个的平均分计入下面对应的表格的score_avg字段里面。
repo_accuracy_score|repo_consistency_score|repo_integrity_score|repo_unq_score
条件1：下面所有在原表的查询需要增加条件:repo = userName/repoName and deleted = 0
条件2：所有在目标表格的更新或插入需要增加repo = userName/repoName，其中userName/repoName为接口入参的拼接
图片文件评价信息合并：
(1)准确性:
图像内容准确性:在content_accuracy_score表格中查询eva_type = "image-content" and file_type = "image" and 条件1的记录，计算score的平均，更新计入repo_accuracy_score表格的score_avg字段里面(更新条件为repo_accuracy_score.eva_rule_type = "imgself-accuracy" and 条件2, 如果没有则进行插入操作)。
(2)完整性:
无信息区域检测:在content_consistency_score表格中查询eva_type = "image-noinfo" and file_type = "image" and 条件1的记录，计算score的平均，更新计入repo_consistency_score表格的score_avg字段里面(更新条件为repo_consistency_score.eva_rule_type = "imgself-consistency-region" and 条件2, 如果没有则进行插入操作)。
无信息噪声检测:在content_consistency_score表格中查询eva_type = "image-noise" and file_type = "image" and 条件1的记录，计算score的平均，更新计入repo_consistency_score表格的score_avg字段里面(更新条件为repo_consistency_score.eva_rule_type = "imgself-consistency-noise" and 条件2, 如果没有则进行插入操作)。
(3)唯一性：
图内信息唯一性原则:在content_unq_score表格中查询eva_type = "image-content" and file_type = "image" and 条件1的记录，计算score的平均，更新计入repo_unq_score表格的score_avg字段里面(更新条件为repo_unq_score.eva_rule_type = "imgself-unq" and 条件2, 如果没有则进行插入操作)
(4)一致性:
图内信息一致性规则:在content_integrity_score表格中查询eva_type = "image-content" and file_type = "image" and 条件1的记录，计算score的平均，更新计入repo_integrity_score表格的score_avg字段里面(更新条件为repo_integrity_score.eva_rule_type = "imgself-integrity" and 条件2, 如果没有则进行插入操作)
文本文件评价信息合并：
(1)准确性:
文本格式准确性检测: 在content_accuracy_score表格中查询eva_type = "text-format" and file_type = "text" and 条件1的记录，计算score的平均，更新计入repo_accuracy_score表格的score_avg字段里面(更新条件为repo_accuracy_score.eva_rule_type = "textself-accuracy-format" and 条件2, 如果没有则进行插入操作)。
文本内容准确性检测：在content_accuracy_score表格中查询eva_type = "text-content" and file_type = "text" and 条件1的记录，计算score的平均，更新计入repo_accuracy_score表格的score_avg字段里面(更新条件为repo_accuracy_score.eva_rule_type = "textself-accuracy-content" and 条件2, 如果没有则进行插入操作)。
(2)完整性:
无信息文本检测:在content_consistency_score表格中查询eva_type = "text-noinfo" and file_type = "text" and 条件1的记录，计算score的平均，更新计入repo_consistency_score表格的score_avg字段里面(更新条件为repo_consistency_score.eva_rule_type = "textself-consistency-noinfo" and 条件2, 如果没有则进行插入操作)。
描述完整性检测:在content_consistency_score表格中查询eva_type = "text-desc" and file_type = "text" and 条件1的记录，计算score的平均，更新计入repo_consistency_score表格的score_avg字段里面(更新条件为repo_consistency_score.eva_rule_type = "textself-consistency-content" and 条件2, 如果没有则进行插入操作)。
(3)唯一性:
文本信息唯一性规则:在content_unq_score表格中查询eva_type = "text-content" and file_type = "text" and 条件1的记录，计算score的平均，更新计入repo_unq_score表格的score_avg字段里面(更新条件为repo_unq_score.eva_rule_type = "textself-unq" and 条件2, 如果没有则进行插入操作)
(4)一致性:
文本信息一致性规则:在content_integrity_score表格中查询eva_type = "text-content" and file_type = "text" and 条件1的记录，计算score的平均，更新计入repo_integrity_score表格的score_avg字段里面(更新条件为repo_integrity_score.eva_rule_type = "textself-integrity" and 条件2, 如果没有则进行插入操作)
***********************************
查询并填充json
查询条件：
条件1:repo = userName/repoName(接口入参userName 和 repoName的拼接)
条件2:deleted = 0
modelScoreImgContentAcc, avgScoreImgContentAcc, evaImgContentAcc = select score_model, score_avg, eva_dsc from repo_accuracy_score where eva_rule_type = "imgself-accuracy" and 条件1 and 条件2

modelScoreTextContentAcc, avgScoreTextContentAcc, evaTextContentAcc = select score_model, score_avg, eva_dsc from repo_accuracy_score where eva_rule_type = "textself-accuracy-content" and 条件1 and 条件2

modelScoreTextFormatAcc, avgScoreTextFormatAcc, evaTextFormatAcc = select score_model, score_avg, eva_dsc from repo_accuracy_score where eva_rule_type = "textself-accuracy-format" and 条件1 and 条件2

modelScoreImgNoinfoCon, avgScoreImgNoinfoCon, evaImgNoinfoCon = select score_model, score_avg, eva_dsc from repo_consistency_score where eva_rule_type = "imgself-consistency-region" and 条件1 and 条件2

modelScoreImgNoiseCon, avgScoreImgNoiseCon, evaImgNoiseCon = select score_model, score_avg, eva_dsc from repo_consistency_score where eva_rule_type = "imgself-consistency-noise" and 条件1 and 条件2

modelScoreTextNoInfoCon, avgScoreTextNoInfoCon, evaTextNoInfoCon = select score_model, score_avg, eva_dsc from repo_consistency_score where eva_rule_type = "textself-consistency-noinfo" and 条件1 and 条件2

modelScoreTextDescCon, avgScoreTextDescCon, evaTextDescCon = select score_model, score_avg, eva_dsc from repo_consistency_score where eva_rule_type = "textself-consistency-content" and 条件1 and 条件2

modelScoreInnerImgUni, avgScoreInnerImgUni, evaInnerImgUni = select score_model, score_avg, eva_dsc from repo_unq_score where eva_rule_type = "imgself-unq" and 条件1 and 条件2

modelScoreInnerTextUni, avgScoreInnerTextUni, evaInnerTextUni = select score_model, score_avg, eva_dsc from repo_unq_score where eva_rule_type = "textself-unq" and 条件1 and 条件2

modelScoreInterTextUni, evaInterTextUni = select score_model, eva_dsc from repo_unq_score where eva_rule_type = "inter-text-unq" and 条件1 and 条件2

modelScoreInterImageUni, evaInterImageUni = select score_model, eva_dsc from repo_unq_score where eva_rule_type = "inter-image-unq" and 条件1 and 条件2

modelScoreInnerImgInt, avgScoreInnerImgInt, evaInnerImgInt = select score_model, score_avg, eva_dsc from repo_integrity_score where eva_rule_type = "imgself-integrity" and 条件1 and 条件2

modelScoreInnerTextInt, avgScoreInnerTextInt, evaInnerTextInt = select score_model, score_avg, eva_dsc from repo_integrity_score where eva_rule_type = "textself-integrity" and 条件1 and 条件2

modelScoreInterImageInt, evaInterImageInt = select score_model, eva_dsc from repo_integrity_score where eva_rule_type = "inter-image-integrity" and 条件1 and 条件2

modelScoreInterTextInt, evaInterTextInt = select score_model, eva_dsc from repo_integrity_score where eva_rule_type = "inter-text-integrity" and 条件1 and 条件2

modelScoreTime, evaTime = select score, eva_dsc from repo_timeliness_score where 条件1 and 条件2

modelScoreEffictive, evaEffictive = select score, eva_dsc from repo_effectiveness_score where 条件1 and 条件2
json格式:
{
	"taskId": taskId,
    "accuracy":{
        "imgContent":{
            "modelScore": modelScoreImgContentAcc,
            "avgScore": avgScoreImgContentAcc,
            "eva":evaImgContentAcc
        },
        "textContent":{
            "modelScore":modelScoreTextContentAcc,
            "avgScore":avgScoreTextContentAcc,
            "eva":evaTextContentAcc
        },
        "textFormat":{
            "modelScore":modelScoreTextFormatAcc,
            "avgScore":avgScoreTextFormatAcc,
            "eva":evaTextFormatAcc
        }
    },
    "consistency":{
        "imgNoInfoRegion": {
            "modelScore":modelScoreImgNoinfoCon,
            "avgScore":avgScoreImgNoinfoCon,
            "eva":evaImgNoinfoCon
        },
        "imgNoise": {
            "modelScore":modelScoreImgNoiseCon,
            "avgScore":avgScoreImgNoiseCon,
            "eva":evaImgNoiseCon
        },
        "textInfo": {
            "modelScore":modelScoreTextNoInfoCon,
            "avgScore":avgScoreTextNoInfoCon,
            "eva":evaTextNoInfoCon
        },
        "textDesc": {
            "modelScore":modelScoreTextDescCon,
            "avgScore":avgScoreTextDescCon,
            "eva":evaTextDescCon
        }
    },
    "unique": {
        "innerImage":{
            "modelScore":modelScoreInnerImgUni,
            "avgScore":avgScoreInnerImgUni,
            "eva":evaInnerImgUni
        },
        "interImage":{
            "modelScore":modelScoreInterImageUni,
            "eva":evaInterImageUni
        },
        "innerText":{
            "modelScore":modelScoreInnerTextUni,
            "avgScore":avgScoreInnerTextUni,
            "eva":evaInnerTextUni
        },
        "interText":{
            "modelScore":modelScoreInterTextUni,
            "eva":evaInterTextUni
        }
    },
    "integrity": {
        "innerImage":{
            "modelScore": modelScoreInnerImgInt,
            "avgScore": avgScoreInnerImgInt,
            "eva":evaInnerImgInt
        },
        "innerText":{
            "modelScore":modelScoreInnerTextInt,
            "avgScore":avgScoreInnerTextInt,
            "eva":evaInnerTextInt
        },
		"interImage":{
            "modelScore":modelScoreInterImageInt,
            "eva":evaInterImageInt
		},
		"interText":{
		    "modelScore":modelScoreInterTextInt,
            "eva":evaInterTextInt
		}
    },
    "time": {
        "modelScore": modelScoreTime,
        "eva": evaTime
    },
    "effictive":{
        "modelScore": modelScoreEffictive,
        "eva": evaEffictive
    }
}
json填充完成之后，将json作为参数调用post接口http://RECALL.IP:RECALL.PORT/RECALL.API。