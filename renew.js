const axios = require('axios');

const API_TOKEN = process.env.PIDGINHOST_API_TOKEN;
const BASE_URL = 'https://www.pidginhost.com/api';

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Authorization': `Token ${API_TOKEN}`,
    'Content-Type': 'application/json',
  },
});

// 代理通过环境变量自动生效

// 计算两个日期相差天数
function daysUntil(targetDate) {
  const now = new Date();
  const diff = new Date(targetDate) - now;
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

async function renew() {
  try {
    console.log('📋 获取未支付发票列表...');
    // 获取所有未支付发票（可能分页，这里简化处理，仅取第一页，可根据需要循环）
    const invoicesRes = await client.get('/billing/invoices/', {
      params: { status: 'unpaid' }  // 假设支持过滤，若不支持则手动过滤
    });
    const invoices = invoicesRes.data.results || invoicesRes.data || [];

    console.log(`📄 找到 ${invoices.length} 张未支付发票`);

    let renewedCount = 0;
    let failedCount = 0;

    for (const invoice of invoices) {
      // 获取发票关联的服务详情
      if (!invoice.service) {
        console.log(`⚠️ 发票 #${invoice.id} 无关联服务，跳过`);
        continue;
      }

      try {
        const serviceRes = await client.get(`/billing/services/${invoice.service}/`);
        const service = serviceRes.data;

        // 检查服务到期时间（假设服务对象中有 expiry_date 字段）
        const expiry = service.expiry_date || service.expires_at || service.next_due_date;
        if (!expiry) {
          console.log(`⚠️ 服务 ${service.id} 无到期时间，跳过`);
          continue;
        }

        const days = daysUntil(expiry);
        console.log(`🕒 服务 ${service.id} (${service.name || '未命名'}) 还有 ${days} 天到期`);

        // 如果到期时间小于等于 7 天，尝试支付该发票
        if (days <= 7) {
          console.log(`💳 尝试支付发票 #${invoice.id} (金额: ${invoice.amount})`);
          await client.post(`/billing/invoices/${invoice.id}/pay-with-funds/`, {});
          console.log(`✅ 发票 #${invoice.id} 支付成功（使用余额）`);
          renewedCount++;
        } else {
          console.log(`⏳ 服务 ${service.id} 暂不需要续期`);
        }
      } catch (err) {
        console.error(`❌ 处理服务 ${invoice.service} 出错:`, err.response?.data || err.message);
        failedCount++;
      }
    }

    console.log(`🎉 续期完成：成功支付 ${renewedCount} 张发票，失败 ${failedCount} 张`);
    if (failedCount > 0) {
      // 通知部分失败，但整体返回成功，后续 TG 会告知
    }
    process.exit(0);
  } catch (error) {
    console.error('❌ 续期过程异常:', error.response?.data || error.message);
    process.exit(1);
  }
}

renew();
