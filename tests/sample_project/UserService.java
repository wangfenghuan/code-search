package com.example.demo.service;

import java.util.ArrayList;
import java.util.List;

/**
 * 用户领域业务服务
 */
public class UserService {

    /**
     * 查询系统全部活跃用户
     */
    public List<String> findAll() {
        List<String> users = new ArrayList<>();
        users.add("admin");
        users.add("guest");
        return users;
    }

    /**
     * 注册或保存用户
     */
    public String save(String user) {
        return "Saved: " + user;
    }
}
