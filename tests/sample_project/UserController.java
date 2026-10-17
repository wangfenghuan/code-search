package com.example.demo.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import com.example.demo.service.UserService;
import java.util.List;

/**
 * 用户 REST 路由控制器
 */
@RestController
@RequestMapping("/api/v1")
public class UserController {
    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    /**
     * 获取系统用户列表接口
     */
    @GetMapping("/users")
    public List<String> getUsers() {
        return userService.findAll();
    }

    /**
     * 创建新用户接口
     */
    @PostMapping("/users")
    public String createUser(String user) {
        return userService.save(user);
    }
}
