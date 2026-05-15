逻辑修改1:
/api/v1/evaluate 的传入参数如下
{"taskId","userName","repoName","branchName","repoIntroduction"}
将taskId去掉，增加evaluate_id，传入格式位number(int8)
taskId转为随机生成32位uuid。
----------------------------------------------------------
形成接口调用应用隔离：
现在在配置文件.env中配置了
APP_KEY=multimodal-eva
APP_SECRET=6f8a1c4e5b2d4f9a8c7e6d5b4a3c2e1f
在调用http://127.0.0.1:18080/api/v1/evaluate时要在头部增加X-App-Key = APP_KEY, X-App-Secret = APP_SECRET
改造如下：
创建数据库表格，表格结构如下：
{
	tableName: 'sys_app',
	fields: {
		id: 'bigserial | PRIMARY KEY | 主键id(自增)',
		app_key: 'VARCHAR(255) | 应用键(唯一)',
		app_secret: 'varchar(32) | 应用密钥, 32位uuid',
		create_at: 'TIMESTAMPTZ DEFAULT NOW() | 创建时间',
		deleted: 'int2 | 是否被删除(默认0)'
	}
}
增加第一个记录(app_key = "multimodal-eva", app_secret = "6f8a1c4e5b2d4f9a8c7e6d5b4a3c2e1f")
新增简易注册接口，入参为{"app_key": "具体appKey", "app_secret": "具体appSecret"}，调用后在sys_app表格中增加相应的记录。调用注册接口必须使用sys_app中id为1的app_key与app_secret，也就是上述新增的记录，新增的app_key不能与sys_app表格中其它app_key重复。
-------------------------------------------------------------
逻辑修改2:
eval_tasks表格增加字段creator(int8), 它被用来记录创建评价任务的app_key的对应表格sys_app主键id；增加evaluate_id(int8)字段, 被用来记录接口传参evaluate_id。
在调用http://127.0.0.1:18080/api/v1/evaluate时不再与配置文件中的APP_KEY、APP_SECRET比较，而是查询sys_app表格内是否存在相应的信息，如果有则调用，创建任务向eval_task表格插入记录时，在creator字段插入app_key = X-App-Key对应sys_app表格中相应记录的主键id;
下列表格中，增加字段task_id，用来与上面创建的任务对应。评价过程中，在下列表格的新增语句中增加task_id属性赋值。
content_accuracy_score
content_consistency_score
content_integrity_score
content_unq_score
repo_accuracy_score
repo_consistency_score
repo_effectiveness_score
repo_integrity_score
repo_timeliness_score
repo_unq_score