# Hermes Custom Gateway Hub (`custom-gateway-hub`)

Plugin mở rộng **100% an toàn khi cập nhật (`hermes update`)** dành cho **Hermes Agent & Hermes Desktop**, giúp kết nối tới bất kỳ OpenAI-compatible Custom Gateway / Proxy nào, tự động quét danh sách model mới (`/v1/models`), phân tách thông minh và cho phép chọn riêng **Model Sinh Nội Dung (Chat/Reasoning)** và **Model Tạo Ảnh (Image Generation)**.

---

## Tính năng chính

- **Tự động & Chủ động Check Connection (`/v1/models`)**:
  - Tự động kiểm tra và đồng bộ model mới khi mở trang (có công tắc bật/tắt, chu kỳ chống spam 60 giây).
  - Nút **`Check Connection & Tải Model mới`** đo độ trễ (`ms`), hiển thị trạng thái kết nối trực quan và gắn nhãn **`MỚI`** cho các model vừa xuất hiện trên Gateway.
- **Tách riêng 2 bảng chọn Model**:
  - **Model Sinh Nội Dung (Chat / Reasoning)**: Tìm kiếm nhanh, lọc theo họ model (`OpenAI / GPT`, `Anthropic / Claude`, `Google / Gemini`, ...), áp dụng tức thì cho phiên chat đang mở mà không cần khởi tạo phiên mới.
  - **Model Tạo Ảnh (Image Generation)**: Đăng ký dynamic provider `custom-gateway` cho công cụ `image_generate` của Hermes, hỗ trợ cả chuẩn `/v1/images/generations` (`gpt-image-*`, `flux-*`, `dall-e-*`) lẫn fallback `/v1/chat/completions` (cho các model như `gemini-3.1-flash-image`).
- **Đồng bộ đa bề mặt**:
  - Mục điều hướng **`Gateway Models`** ở thanh Sidebar bên trái (`/gateway-hub`).
  - Chip hiển thị nhanh Model Tạo Ảnh đang dùng ở góc phải thanh trạng thái (`StatusBar`).
  - Trang cấu hình trong **Settings → Plugins → Custom Gateway Hub** và lệnh nhanh trong **Command Palette (`Ctrl+K`)**.
  - Tùy chọn tự động đồng bộ biến môi trường tạo ảnh sang skill `ppt-master` (`skills/productivity/ppt-master/.env`).
- **Không đụng vào mã lõi `hermes-agent/`**:
  - Mọi file nằm gọn trong `$HERMES_HOME/plugins/custom-gateway-hub` và `$HERMES_HOME/desktop-plugins/custom-gateway-hub`, không bao giờ bị ghi đè hay xung đột Git khi chạy `hermes update`.

---

## Cấu trúc thư mục

```text
├── plugins/
│   └── custom-gateway-hub/
│       ├── plugin.yaml              # Manifest backend plugin
│       ├── __init__.py              # CustomGatewayImageProvider (image_gen registry)
│       ├── gateway_core.py          # Bộ lõi /v1/models probe, phân loại model & lưu cấu hình
│       └── dashboard/
│           ├── manifest.json        # Khai báo hot-mount API cho Hermes Dashboard/Desktop
│           └── plugin_api.py        # FastAPI routes: GET /state, POST /check, POST /apply
├── desktop-plugins/
│   └── custom-gateway-hub/
│       └── plugin.js                # Giao diện Hermes Desktop (chuẩn @hermes/plugin-sdk ESM)
├── config.example.yaml              # Cấu hình mẫu không chứa khóa nhạy cảm
└── install.ps1                      # Script cài đặt nhanh sang máy khác trên Windows
```

---

## Cài đặt nhanh trên máy mới

### Cách 1: Chạy script cài đặt (Windows PowerShell)

```powershell
git clone https://github.com/xuanhoatrieu/hermes-custom-gateway-hub.git
cd hermes-custom-gateway-hub
.\install.ps1
```

### Cách 2: Cấu hình biến môi trường & kích hoạt

1. Thêm khóa API vào `$HERMES_HOME/.env`:
   ```env
   HERMES_CUSTOM_CUSTOM_GATEWAY_API_KEY=sk-your-api-key
   ```
2. Bật plugin trong `$HERMES_HOME/config.yaml` (xem chi tiết tại [`config.example.yaml`](./config.example.yaml)):
   ```yaml
   plugins:
     enabled:
       - custom-gateway-hub
   ```
3. Mở **Hermes Desktop**, nhấn `Ctrl + K` → chọn **`Reload desktop plugins`**, sau đó mở mục **`Gateway Models`** ở thanh bên trái để kiểm tra kết nối và chọn model.

---

## Giấy phép

MIT License.
