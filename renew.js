const axios = require('axios');

const API_TOKEN = process.env.PIDGINHOST_API_TOKEN;
const BASE_URL = 'https://www.pidginhost.com/api';

// 创建 axios 实例
const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Authorization': `Token ${API_TOKEN}`,
    'Content-Type': 'application/json',
  },
});

// 代理配置（如果环境变量存在）
if (process.env.HTTP_PROXY) {
  // axios 通过环境变量自动使用代理
}

async function renew() {
  try {
    console.log('🔄 开始获取服务列表...');
    
    // 1. 获取所有云服务器列表
    // 参考: https://www.pidginhost.com/api/schema/swagger-ui/
    const serversRes = await client.get('/cloud/servers/');
    const servers = serversRes.data.data || serversRes.data;
    
    console.log(`📋 找到 ${servers.length} 台服务器`);
    
    let renewedCount = 0;
    
    for (const server of servers) {
      // 检查服务器是否需要续期（根据你的业务逻辑判断）
      // 例如：检查到期时间，如果小于7天则续期
      const expiryDate = new Date(server.expiry_date);
      const now = new Date();
      const daysUntilExpiry = (expiryDate - now) / (1000 * 60 * 60 * 24);
      
      if (daysUntilExpiry <= 7) {
        console.log(`🔄 正在续期服务器: ${server.name || server.id} (${daysUntilExpiry.toFixed(1)}天后到期)`);
        
        // 2. 执行续期操作
        // 注意：具体续期接口需要根据实际 API 文档确认
        // 可能的接口: POST /cloud/servers/{id}/renew/
        // 或 PATCH /cloud/servers/{id}/
        const renewRes = await client.post(`/cloud/servers/${server.id}/renew/`, {
          // 续期参数，根据实际 API 调整
          // 例如: period: 1, unit: 'month'
        });
        
        if (renewRes.status === 200 || renewRes.status === 201) {
          console.log(`✅ 服务器 ${server.name || server.id} 续期成功`);
          renewedCount++;
        } else {
          console.log(`⚠️ 服务器 ${server.name || server.id} 续期返回: ${renewRes.status}`);
        }
      } else {
        console.log(`⏳ 服务器 ${server.name || server.id} 暂不需要续期 (${daysUntilExpiry.toFixed(1)}天后到期)`);
      }
    }
    
    console.log(`🎉 续期完成，共续期 ${renewedCount} 台服务器`);
    return { success: true, renewedCount };
    
  } catch (error) {
    console.error('❌ 续期失败:', error.response?.data || error.message);
    throw error;
  }
}

// 执行续期
renew()
  .then(() => process.exit(0))
  .catch(() => process.exit(1));
